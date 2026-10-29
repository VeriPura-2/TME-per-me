# Deploy to Cloud Run (private staging, EU)

Run in Cloud Shell, project 181473838676:

    gcloud config set project 181473838676
    gcloud services enable run.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com
    # let the Cloud Run service account read the key
    gcloud secrets add-iam-policy-binding ANTHROPIC_API_KEY \
      --member="serviceAccount:181473838676-compute@developer.gserviceaccount.com" \
      --role="roles/secretmanager.secretAccessor"
    git clone https://github.com/VeriPura-2/TME-per-me && cd TME-per-me
    gcloud run deploy via-libera-staging --source . --region europe-west1 --no-allow-unauthenticated

Test with your own identity token:

    curl -X POST "$(gcloud run services describe via-libera-staging --region europe-west1 --format='value(status.url)')/chat" \
      -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
      -H "Content-Type: application/json" \
      -d '{"message":"We make pasta in Puglia and want to export to the UK"}'

## Stripe (test mode)

Payments switch on by themselves when the secret `STRIPE_SECRET_KEY` exists in Secret Manager (checked every minute, no redeploy needed once the code is deployed). A `sk_test_` key runs test mode. A live key is refused unless the env var `STRIPE_ALLOW_LIVE=1` is set. Without a key the simulated payment stays on.

1. Store the keys (never in chat):

        read -s K; printf %s "$K" | gcloud secrets create STRIPE_SECRET_KEY --data-file=-; unset K
        gcloud secrets add-iam-policy-binding STRIPE_SECRET_KEY --member=serviceAccount:via-libera-app@via-libera-staging.iam.gserviceaccount.com --role=roles/secretmanager.secretAccessor

2. In the Stripe dashboard (test mode) add a webhook endpoint:
   `https://via-libera-staging-181473838676.europe-west1.run.app/stripe/webhook`
   Events: `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_failed`, `charge.refunded`, `charge.dispute.created`.
   Copy its signing secret (`whsec_...`) and store it the same way as `STRIPE_WEBHOOK_SECRET` (create the secret, then grant the same accessor role).
3. Stripe dashboard, Settings, Billing, Customer portal (test mode): allow updating the payment method and cancelling the subscription. Do not allow plan switching (plans are created at checkout, so switching goes through our Services screen).
4. Optional env var `PUBLIC_BASE_URL` (for example `https://via-libera-staging-181473838676.europe-west1.run.app`). Without it the address comes from the request.
5. Try it: Services screen, choose a paid plan or approve items and press Pay. Test card `4242 4242 4242 4242`, any future date, any CVC. The return page confirms with Stripe directly, so the result shows even if the webhook is not set up yet. The webhook keeps the plan in step later (renewals, cancellations).

Removal checklist when going live: remove `sim/payment.py` and the `/simpay` route, set feature `payment` to live, replace `sim/prices.py` with the real price menu (menu.py), set `STRIPE_ALLOW_LIVE=1` with the live key, and remove the example invite credit used in test mode (`stripe_pay._plan_active`).
