# Trial-limit data audit — pronouncethis.us (accent-coach-pro)

**Read-only query. Nothing was changed.**
- Deployment: accent-coach-pro (live at https://accent-coach-pro.emergent.host, custom domain pronouncethis.us)
- Active run queried: `8df0a446-bdbe-4c30-bf5e-da3a202f5678`
- Database (resolved from DB_NAME): `accent-coach-pro-test_database`
- Trial limit per spec: TRIAL_WORD_LIMIT=2; gate usage = max(len(trial_words), trial_word_used)

---

## 1. `users` — docs with trial_word_used > 2 OR size(trial_words) > 2  (3 found)

### a) g***@icloud.com
- trial_word_used: **5**
- trial_scene_used: 1
- trial_words (5): ["warrior","america","moth","fountain","party"]
- created_at: 2026-09-28T06:09:49Z
- last_login_at: 2026-09-28T06:09:49Z
- Membership fields present: **stripe_customer_id = cus_VLERxdkcKvHGkJ**, last_stripe_sync_at = 2026-09-28T06:21:42Z. NO stripe_subscription_status, NO kajabi / grants / manual-access fields.
- Note: trial_word_used (5) == len(trial_words) (5). Both agree — this user genuinely consumed 5 words.

### b) p***@gmail.com
- trial_word_used: **5**
- trial_scene_used: 1
- trial_words (1): ["realise"]
- created_at: 2026-10-23T09:22:05Z
- last_login_at: 2026-10-23T09:22:05Z
- Membership fields present: last_stripe_sync_at = 2026-10-23T09:22:06Z only. NO stripe_customer_id, NO subscription_status, NO kajabi / grants / manual fields.
- Note: **mismatch** — trial_word_used=5 but trial_words holds only 1 entry. Counter was incremented 5× while the array only kept 1 word.

### c) n***@icloud.com
- trial_word_used: **4**
- trial_scene_used: 1
- trial_words (2): ["vision","isn't"]
- created_at: 2026-10-25T08:47:14Z
- last_login_at: 2026-10-25T08:47:14Z
- Membership fields present: last_stripe_sync_at = 2026-10-25T09:08:29Z only. NO stripe_customer_id, NO subscription_status, NO kajabi / grants / manual fields.
- Note: **mismatch** — trial_word_used=4 but trial_words holds 2 entries.

---

## 2. `trial_devices` — docs with trial_word_used > 2 OR size(trial_words) > 2  (3 found)
(No `blocked` field exists on any of these docs — reported as "absent".)

| device_id (first 8) | trial_word_used | trial_words | emails (masked) | blocked |
|---|---|---|---|---|
| yt5cf-p4 | 5 | ["warrior","america","moth","fountain","party"] | g***@icloud.com | absent |
| EXrZf-Fi | 5 | ["realise"] | p***@gmail.com | absent |
| WIfrHENU | 4 | ["vision","isn't"] | n***@icloud.com | absent |

The three trial_devices mirror the three users 1:1 (same counts, same words).

---

## 3. Counts

- **Total users: 65**

| trial_word_used | user count |
|---|---|
| 0 | 53 |
| 1 | 4 |
| 2 | 5 |
| 3 | 0 |
| 4 | 1 |
| 5 | 2 |
| >5 | 0 |
| (field missing) | 0 |

Sum = 65 (matches total). All users have a numeric trial_word_used.

---

## Observations (for the owner — not a code change applied by me)
- Three accounts/devices exceeded the limit of 2: counts of 4, 5, 5.
- In 2 of the 3 (p***@gmail, n***@icloud) `trial_word_used` is LARGER than `len(trial_words)`. Because the gate uses `max(len(trial_words), trial_word_used)`, the counter alone should have blocked them at 2 — yet it reached 4/5. This points at the increment path advancing the counter without the gate actually denying at >=2 (e.g. the gate check running before the increment, a client that doesn't re-check require_access() per word, or the counter being bumped on a path that bypasses the gate).
- Only g***@icloud.com carries a `stripe_customer_id`; none of the three carry a `stripe_subscription_status` or any kajabi/grants/manual access field — so none of them appears to be a paid member who should have unlimited access. The overage is not explained by membership.
- This is a data/logic question, not a runtime crash — backend logs show no error for this; the signal is entirely in the data above.
