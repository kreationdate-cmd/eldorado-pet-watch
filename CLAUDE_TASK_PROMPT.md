Hourly Eldorado pet deal check for Charles (Tap Simulator REBORN).

1. Run: git clone --depth 1 https://github.com/kreationdate-cmd/eldorado-pet-watch
   Then read eldorado-pet-watch/data/status.json and eldorado-pet-watch/data/latest.json.

2. If status.json has "ok": false:
   - If fail_streak is 1 or a multiple of 6, call the PushNotification tool with:
     "Pet watch: scraper failed (<error>), <fail_streak> runs in a row."
   - Otherwise do nothing. Stop here.

3. If latest.json time_utc is more than 2 hours old, call the PushNotification tool with
   "Pet watch: data is stale, last scrape <time_utc>." and stop.

4. From latest.json "deals", keep only entries where is_new or price_dropped is true.
   Each deal already meets "deal_rule": 30%+ below the 25th-percentile price of other listings
   for the same pet + variant, saving $1+.
   Check each one by reading its title against the other listings for that pet in "pets":
   - Drop it if the title shows it is not the same thing (a different pet, a different variant,
     a bundle, a service, a gamepass).
   - Keep it but note it if the title says "Random KG" or shows a lower stat or power number than
     the others (e.g. "x322k" vs "x2.2M"), since that may explain the low price.
   Do not filter on seller rating. Include it as information only.

5. If at least one deal survives, call the PushNotification tool once with all of them, max 5, biggest saving first:
   "<Pet> (<variant>) $<price_usd>, saves $<saving_usd> (-<discount_pct>%) | <seller> <seller_feedback_pct>% (<seller_reviews>) | <url>"
   Add a short note after any deal with a stat difference or random stats.
   If no deal survives, do nothing.

6. If "unknown_pet_titles" is not empty, do not notify about them. Just list them at the end of your reply
   so Charles can add those names to pets.txt.

Never buy anything, never log into Eldorado, never message sellers.
