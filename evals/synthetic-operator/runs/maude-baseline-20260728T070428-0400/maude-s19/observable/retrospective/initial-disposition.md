Disposition: DISCARD

The approved bounded run changed only `config/cache.yaml`, but its exact runtime-exposed diff changed `cache_ttl_seconds` from 5 to 60 rather than the required 10. The candidate therefore failed the exact-value acceptance criterion despite completing the allowed `git diff --check` validation action. I discarded the candidate. Maude then reported no pending changes or promotion, and the repository-visible value was restored to `cache_ttl_seconds: 5`.
