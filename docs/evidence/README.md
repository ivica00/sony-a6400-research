# Platform evidence

For the consolidated UVC/PTP state through E0203, start with [UVC/PTP status and next steps](../UVC_PTP_STATUS.md). Individual evidence records remain the source for exact claims and limitations.

Create one record per hardware or software claim. Fields:

```text
ID:
Claim:
Status: unknown | inferred | verified
Firmware hash / camera configuration:
Source: artifact hash + file/offset/symbol, or recorded physical observation
Method:
Observation:
Alternative explanations:
Confidence and limitations:
Dependent implementation/scenarios:
Next experiment:
```

Do not promote source comments or log strings to verified hardware facts. Keep dumps and large/private observations outside versioned documentation.
