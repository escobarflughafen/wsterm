#lang racket/base
;; -----------------------------------------------------------------------------
;; The import merge, as an executable specification.
;;
;; pipeline/store.py is the implementation; this is the argument it implements.
;; Run it:  racket docs/merge.rkt
;;
;; The problem.  Wealthsimple exports overlap.  You download the full history
;; every month, so today's file restates most of last month's.  A naive append
;; doubles everything; a naive "skip what I already have" keeps a row the broker
;; has since corrected, or deleted.  Both happened here: an OPEN option contract
;; appeared twice because a re-export restated its unit price from 0.18 to 18.
;;
;; The rule.  Inside the date range a file covers, for the accounts it covers,
;; that file is the truth.  Outside it, nothing is touched.  So an export is
;; authoritative for its own window and silent everywhere else -- which is what
;; makes a partial range safe to import and a full history safe to re-import.
;; -----------------------------------------------------------------------------
(require racket/list racket/string racket/format)

;; A row is a hash.  Ten fields identify it; the rest may be restated later.
(define identity-columns
  '(date time account kind sub symbol currency quantity net))

(define (row-key r)
  (for/list ([c identity-columns]) (hash-ref r c #f)))

;; Description, settlement date and unit price are NOT identity: those are
;; exactly the fields a broker corrects after settlement.
(define (row-differs? a b)
  (for/or ([(k v) (in-hash a)]) (not (equal? v (hash-ref b k #f)))))

;; --- coverage ----------------------------------------------------------------
;; What a file is authoritative for: per account, the span of dates it contains.
(define (coverage rows)
  (for/fold ([spans (hash)]) ([r rows])
    (define acct (hash-ref r 'account))
    (define d (hash-ref r 'date))
    (define lo+hi (hash-ref spans acct (cons d d)))
    (hash-set spans acct (cons (string-min d (car lo+hi))
                               (string-max d (cdr lo+hi))))))

(define (string-min a b) (if (string<=? a b) a b))
(define (string-max a b) (if (string<=? a b) b a))

(define (in-span? spans acct date)
  (define s (hash-ref spans acct #f))
  (and s (string<=? (car s) date) (string<=? date (cdr s))))

;; --- the merge ---------------------------------------------------------------
;; Files arrive oldest first; a later file overrides an earlier one inside the
;; window they share.  Counts matter: two genuinely identical fills are two rows,
;; so the unit of work is (key -> how many), not a set.
(define (merge existing files)
  (define-values (covered incoming by-key)
    (for/fold ([covered (hash)] [incoming (hash)] [by-key (hash)]) ([rows files])
      (define spans (coverage rows))
      ;; A later file speaks for its whole window, including saying "no longer
      ;; there".  Dropping the earlier file's rows inside that window first is
      ;; what lets a removal propagate; keeping the larger count would not.
      (define kept-incoming
        (for/hash ([(k n) (in-hash incoming)]
                   #:unless (in-span? spans (list-ref k 2) (list-ref k 0)))
          (values k n)))
      (define kept-by-key
        (for/hash ([(k r) (in-hash by-key)]
                   #:unless (in-span? spans (list-ref k 2) (list-ref k 0)))
          (values k r)))
      (values
       ;; coverage accumulates across files: the union of every window seen
       (for/fold ([c covered]) ([(acct s) (in-hash spans)])
         (define have (hash-ref c acct s))
         (hash-set c acct (cons (string-min (car have) (car s))
                                (string-max (cdr have) (cdr s)))))
       (for/fold ([acc kept-incoming]) ([r rows])
         (hash-update acc (row-key r) add1 0))
       (for/fold ([acc kept-by-key]) ([r rows])
         (hash-set acc (row-key r) r)))))          ; last file wins the field values

  ;; Split what we already have: inside any covered window it is superseded,
  ;; outside it, it stands untouched.
  (define-values (replaced-rows kept)
    (partition (λ (r) (in-span? covered (hash-ref r 'account) (hash-ref r 'date)))
               existing))
  (define replaced
    (for/fold ([acc (hash)]) ([r replaced-rows]) (hash-update acc (row-key r) add1 0)))

  (define merged
    (sort (append kept
                  (for*/list ([(k n) (in-hash incoming)] [_ (in-range n)])
                    (hash-ref by-key k)))
          (λ (a b) (string<? (string-append (hash-ref a 'date) (hash-ref a 'time))
                             (string-append (hash-ref b 'date) (hash-ref b 'time))))))

  (values
   merged
   (hash 'added     (for/sum ([(k n) (in-hash incoming)]) (max 0 (- n (hash-ref replaced k 0))))
         'removed   (for/sum ([(k n) (in-hash replaced)]) (max 0 (- n (hash-ref incoming k 0))))
         'restated  (for/sum ([(k n) (in-hash incoming)])
                      (if (and (hash-ref replaced k #f)
                               (for/or ([r replaced-rows] #:when (equal? (row-key r) k))
                                 (row-differs? (hash-ref by-key k) r)))
                          1 0))
         'untouched (length kept))))

;; -----------------------------------------------------------------------------
;; The case this was written for.
;; -----------------------------------------------------------------------------
(define (row date time account kind symbol qty net #:price [price "0"] #:desc [desc ""])
  (hash 'date date 'time time 'account account 'kind kind 'sub "BUY"
        'symbol symbol 'currency "USD" 'quantity qty 'net net
        'price price 'desc desc))                  ; price and desc are restatable

;; September's export: the option buy, as first reported.
(define sept
  (list (row "2026-09-16" "10:00" "A1" "Trade" "XEQT" "5" "-227")
        (row "2026-09-17" "12:29" "A1" "Trade" "OPEN 261002C00002500" "4" "-72"
             #:price "0.18" #:desc "Bought 4 contract")))

;; October's export covers the same days and corrects the contract's unit price.
;; Identity is unchanged -- same date, time, account, symbol, quantity, net --
;; so it restates rather than duplicates.  Under "append what I don't have",
;; the changed price would have made it a new row: 8 contracts, not 4.
(define oct
  (list (row "2026-09-16" "10:00" "A1" "Trade" "XEQT" "5" "-227")
        (row "2026-09-17" "12:29" "A1" "Trade" "OPEN 261002C00002500" "4" "-72"
             #:price "18" #:desc "Bought 4 contract, FX Rate: 1.3985")
        (row "2026-09-21" "11:51" "A1" "Trade" "NVDA" "-5" "1140")))

(define (show label rows stats)
  (printf "\n~a\n" label)
  (printf "  added ~a · removed ~a · restated ~a · untouched outside the window ~a\n"
          (hash-ref stats 'added) (hash-ref stats 'removed)
          (hash-ref stats 'restated) (hash-ref stats 'untouched))
  (for ([r rows])
    (printf "    ~a ~a  ~a ~a  qty ~a  price ~a\n"
            (hash-ref r 'date) (hash-ref r 'time)
            (~a (hash-ref r 'symbol) #:min-width 22)
            (hash-ref r 'currency) (hash-ref r 'quantity) (hash-ref r 'price))))

(module+ main
  (define-values (m1 s1) (merge '() (list sept)))
  (show "1. first import — nothing held yet" m1 s1)

  (define-values (m2 s2) (merge m1 (list oct)))
  (show "2. October restates the contract price and adds one trade" m2 s2)

  (define-values (m3 s3) (merge m2 (list oct)))
  (show "3. the same file again — re-importing is a no-op" m3 s3)

  ;; A row the broker withdraws disappears -- but only where the new file still
  ;; has authority.  Here 09-21 keeps a row, so the window still reaches it, and
  ;; the cancelled second fill is dropped.
  (define oct+2 (append oct (list (row "2026-09-21" "14:02" "A1" "Trade" "AAPL" "2" "-460"))))
  (define-values (m4a _s) (merge m2 (list oct+2)))
  (define withdrawn (filter (λ (r) (not (equal? (hash-ref r 'symbol) "AAPL"))) oct+2))
  (define-values (m4 s4) (merge m4a (list withdrawn)))
  (show "4. a cancelled fill is withdrawn — the window still covers that day" m4 s4)

  ;; The limitation this design has, stated rather than hidden: coverage is
  ;; derived from the rows a file contains, so a file that drops the ONLY row on
  ;; a date no longer reaches that date, and the old row stands.  Removing a
  ;; lone trade takes a re-import, not a re-export.
  (define short (filter (λ (r) (string<=? (hash-ref r 'date) "2026-09-17")) oct))
  (define-values (m6 s6) (merge m2 (list short)))
  (show "6. a file that stops at 09-17 cannot remove the 09-21 trade" m6 s6)

  ;; And a narrow file touches only its own days.
  (define narrow (list (row "2026-09-21" "11:51" "A1" "Trade" "NVDA" "-5" "1140")))
  (define-values (m5 s5) (merge m2 (list narrow)))
  (show "5. a one-day export — the 16th and 17th are left alone" m5 s5))
