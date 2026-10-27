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
