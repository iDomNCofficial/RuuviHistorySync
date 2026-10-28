# First GitHub release checklist

1. Keep the existing public `iDomNCofficial/RuuviHistorySync` repository active and GitHub Issues enabled.
2. Keep GitHub Issues enabled.
3. Set a short repository description, for example: `Home Assistant integration that backfills RuuviTag internal history after Bluetooth outages.`
4. Add repository topics: `home-assistant`, `hacs`, `ruuvi`, `ruuvitag`, and `bluetooth`.
5. Push the `main` branch and wait for both HACS and Hassfest jobs to pass.
6. Create a GitHub release named `v1.0.0` from the `1.0.0` tag. HACS requires a full release, not only a tag, for default-store submission.
7. Add the repository to HACS as a custom integration and verify a clean installation.
8. Optionally submit the repository to the default HACS catalog after the release and validation checks pass.
