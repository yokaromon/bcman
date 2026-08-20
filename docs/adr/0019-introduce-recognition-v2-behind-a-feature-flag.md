---
status: accepted
---

# Introduce Recognition Pipeline V2 behind a feature flag

After a frozen Recognition Release passes every pickup acceptance gate, merge its production integration with `recognition_pipeline_v2` disabled. An administrator may enable it only for selected new images during the pilot; existing registered Business Cards are not reprocessed automatically, and V1 and V2 never update the same Contact. Make V2 the default for new work only after an explicit stability decision, while retaining V1 as the rollback path through the observation period.
