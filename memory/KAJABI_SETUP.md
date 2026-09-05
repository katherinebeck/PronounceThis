# Kajabi Setup Guide — Accent Coach (PRODUCTION)

Your app is now live at **https://accent-coach-pro.emergent.host** 🎉

Follow these steps in order. Anything in `code blocks` should be copied exactly.

---

## Your production webhook URLs

Paste this exact URL into every Kajabi **webhook** field (steps 5 + 6):

```
https://accent-coach-pro.emergent.host/api/kajabi/webhook?token=zvL9oWLagHxluDmEncG_Yx_C72xPh0eez3cV6eDsCFw
```

And this URL for the **cancellation Automation** (step 7):

```
https://accent-coach-pro.emergent.host/api/kajabi/cancel?token=zvL9oWLagHxluDmEncG_Yx_C72xPh0eez3cV6eDsCFw
```

> Keep the `?token=...` part — it's what proves the request is really from Kajabi. Don't share it publicly.

---

## Step 1 — Create the Monthly Offer

1. Open Kajabi Admin
2. Left sidebar → **Sales → Offers** (or **Sales → Pricing**)
3. Click **+ New Offer**
4. Name it: **Accent Coach — Monthly**
5. Price: set your monthly price (e.g., $19/mo)
6. Billing: **Subscription — Recurring**, billed monthly
7. Save

## Step 2 — Create the Annual Offer

Repeat step 1 with:
- Name: **Accent Coach — Annual**
- Billing: **Subscription — Recurring**, billed yearly
- Consider pricing it at 10× the monthly rate (2 free months as an incentive)

## Step 3 — Create the Group Coaching Free Grant (optional)

Repeat step 1 with:
- Name: **Accent Coach — Group Coaching Access**
- Price: **Free** (or bundle it inside your existing group coaching offer)
- This grants app access to your paid coaching students at no extra charge

---

## Step 4 — Grab the checkout URLs (send these to me)

For each offer you created:

1. Open the offer → **Checkout** tab → **Copy Checkout Link**
2. Send them to me in the chat like this:
   ```
   Monthly:  https://katherinebeck.mykajabi.com/offers/xxxxxxxx
   Annual:   https://katherinebeck.mykajabi.com/offers/xxxxxxxx
   Group:    https://katherinebeck.mykajabi.com/offers/xxxxxxxx  (optional)
   ```

I'll paste them into the production env and redeploy (~2 min) — then the paywall buttons go live.

---

## Step 5 — Add the Purchase Created webhook (per offer)

For EACH of the 3 offers above:

1. Open the offer
2. Click the **⋯ (More)** menu → **Webhooks**
3. **+ Add Webhook**
4. Paste this URL:
   ```
   https://accent-coach-pro.emergent.host/api/kajabi/webhook?token=zvL9oWLagHxluDmEncG_Yx_C72xPh0eez3cV6eDsCFw
   ```
5. Save
6. If Kajabi shows a **Send Test** button, click it and tell me — I'll confirm it arrived.

---

## Step 6 — Add the site-wide Payment Succeeded webhook

This one is for recurring monthly renewals.

1. **Settings → Third-Party Integrations → Webhooks** (or **Settings → Integrations & Webhooks**)
2. **+ Create Webhook**
3. Event: **Payment Succeeded**
4. URL:
   ```
   https://accent-coach-pro.emergent.host/api/kajabi/webhook?token=zvL9oWLagHxluDmEncG_Yx_C72xPh0eez3cV6eDsCFw
   ```
5. Save

---

## Step 7 — Cancellation Automation

Kajabi doesn't send a native cancellation webhook, so we use an Automation.

For EACH subscription offer (Monthly + Annual):

1. **Marketing → Automations → + New Automation**
2. Name: **Accent Coach — Cancel access**
3. Trigger: **Recurring payments cancellation initiated** (choose the offer)
4. Action: **Send HTTP request** (or **Webhook** action)
   - Method: **POST**
   - URL:
     ```
     https://accent-coach-pro.emergent.host/api/kajabi/cancel?token=zvL9oWLagHxluDmEncG_Yx_C72xPh0eez3cV6eDsCFw
     ```
   - Content-Type: `application/json`
   - Body:
     ```json
     {
       "email": "{{contact.email}}",
       "subscription_end_at": "{{purchase.effective_end_at}}"
     }
     ```
     _(If Kajabi's tag syntax is different, tell me what merge fields are available — I'll adjust.)_
5. Save + Activate

Result: when someone cancels, they keep access until their current paid period ends, then they're bumped back to trial state.

---

## Step 8 — Test the full flow

1. Sign into the app at https://accent-coach-pro.emergent.host (use the email you signed up to Resend with — that's the only address Resend delivers to until we verify `katherinebeck.com`)
2. Try uploading a scene → after 1 upload, the paywall should appear with Monthly + Annual buttons (once you've completed step 4)
3. Click Monthly → complete a real (or discounted test) purchase in Kajabi
4. Refresh the app → your account chip should say **"Accent Coach — Monthly"**
5. Cancel the subscription inside Kajabi → check that your access still works until `subscription_end_at` passes

---

## Troubleshooting

- **Webhook shows "test failed"** — double-check the URL includes the entire `?token=…` string
- **Paywall shows "Memberships coming soon"** instead of buttons — the Monthly/Annual offer URLs aren't in the app env yet (I'll paste them once you send them in step 4)
- **Login link never arrives** — Resend is currently in test mode. Only emails to the address you signed up to Resend with will be delivered. Once we verify `katherinebeck.com` in Resend (see resend.com → Domains), links come from `login@katherinebeck.com` and go to any student.
