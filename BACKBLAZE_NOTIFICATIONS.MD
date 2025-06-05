# API: `b2_get_bucket_notification_rules`

**Method:** `GET`
**Endpoint:** `/b2api/v4/b2_get_bucket_notification_rules`

Lists bucket event notification rules alphabetically by rule name.
This will return an error if called on a non-existent `bucketId`.

## Header Parameters

*   `Authorization` (string, required):
    An account authorization token, obtained from `b2_authorize_account`. The token must have the `readBucketNotifications` capability.

## Query Parameters

*   `bucketId` (string, required):
    The unique identifier for the bucket containing the event notification rules.

## Responses

*   **200 OK**: The request succeeded.
    *   **Content-Type**: `application/json`
    *   **Body Structure**:
        ```json
        {
          "bucketId": "string",
          "eventNotificationRules": [
            {
              "eventTypes": ["string"],
              "isEnabled": "boolean",
              "isSuspended": "boolean",
              "maxEventsPerBatch": "integer",
              "name": "string",
              "objectNamePrefix": "string",
              "suspensionReason": "string",
              "targetConfiguration": {
                "customHeaders": [
                  {
                    "name": "string",
                    "value": "string"
                  }
                ],
                "hmacSha256SigningSecret": "string", // Opaque identifier or name for the secret on B2's side
                "targetType": "string", // e.g., "webhook"
                "url": "string"
              }
            }
          ]
        }
        ```

        **Field Descriptions (within `eventNotificationRules` objects):**
        *   `eventTypes` (array of string): List of event types. Example: `["b2:ObjectCreated:*"]`
        *   `isEnabled` (boolean): Whether the rule is enabled. Example: `true`
        *   `isSuspended` (boolean): Whether the rule is suspended. Example: `false`
        *   `maxEventsPerBatch` (integer): Max events per webhook invocation (1-50, default 1). Example: `1`
        *   `name` (string): Unique name for the rule. Example: `mySampleRule1`
        *   `objectNamePrefix` (string): Object name prefix for the rule. Example: `images/`
        *   `suspensionReason` (string): Reason for suspension, if any. Example: `"A reason for suspension"`
        *   `targetConfiguration` (object): Target configuration.
            *   `targetType` (string): Currently only `"webhook"`.
            *   **(Webhook-specific fields within `targetConfiguration`):**
                *   `customHeaders` (array of objects): Custom headers. Example: `[{"name": "X-MyHeader", "value": "MyValue"}]`
                *   `hmacSha256SigningSecret` (string): Identifier for the signing secret on B2's side. Example: `MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0`
                *   `url` (string): The webhook URL. Example: `https://www.example.com/sampleurl` 