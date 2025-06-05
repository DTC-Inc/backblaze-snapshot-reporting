# Event Notifications Reference Guide

This article provides information about Backblaze B2 Cloud Storage Event Notifications such as rule structure, event types, and webhooks.

*   To create and use Event Notifications (UI guide), click [here](https://www.backblaze.com/b2/docs/event_notifications.html).
*   You can also use the Backblaze B2 API to manage Event Notifications:
    *   [Get Bucket Notification Rules (`b2_get_bucket_notification_rules`)](https://www.backblaze.com/b2/docs/apis/b2_get_bucket_notification_rules.html)
    *   [Set Bucket Notification Rules (`b2_set_bucket_notification_rules`)](https://www.backblaze.com/b2/docs/apis/b2_set_bucket_notification_rules.html)

**Note:**
*   To enable this feature, contact the Support team to request access.
*   Currently, Group admins cannot manage Event Notification rules in a Group member's account.

## Event Notification Rules

Event Notifications instruct Backblaze B2 to perform actions when certain events happen in the system. You can set up rules to trigger a webhook. An HTTP POST request is sent to a URL that you configure whenever certain events occur, such as an object upload or an object being created in a destination bucket during replication.

A bucket can have up to 25 Event Notifications. Event Notification rules are not supported for object download events or for replication of objects from a source bucket. All webhook invocations use the POST HTTP method and must use HTTPS protocol. You must allow incoming requests to your webhook endpoint from the IP address blocks that are listed in the [Backblaze IP Address List](https://www.backblaze.com/b2/docs/ip_address_list.html).

### Event Notification Rule Structure

Each Event Notification rule can have the following parameters:

*   `eventTypes` (required, array of strings):
    Events to which the rule applies. For more information, see "Event Types" below.
*   `isEnabled` (required, boolean):
    Specifies whether the Event Notification rule is enabled. Possible values are `true` or `false`. By default, the value is set to `true` (enabled).
*   `name` (required, string):
    A name for identifying the rule. Names must be unique within a bucket. Names can consist only of uppercase and lowercase English letters, numbers, and hyphens (`-`). A name must be between six and 63 characters long. Names that start with `b2-` are reserved for Backblaze use.
    *Examples of valid names are `myObjectUploadRule` and `mycompany-webhooks`.*
*   `objectNamePrefix` (required, string):
    Specifies the objects in the bucket in which the Event Notification rule applies. Objects with names that begin with `objectNamePrefix` are subject to the rule. An empty string prefix `""` means that the rule applies to all of the objects in the bucket. The `objectNamePrefix` must not overlap with another `objectNamePrefix` for the same event type. For example, an Event Notification rule with the prefix `"images/pets/"` is not allowed if there is an existing rule of the same event type with `"images/"`.
*   `customHeaders` (required, array of objects):
    A set of name/value pairs for custom headers that are added to the webhook invocation. For example, this can be a bearer token. There can be at most 10 custom header name/value pairs. The total number of URL-encoded bytes must not exceed 2,048. Each custom header name/value pair has three extra bytes added to the total, accounting for the `:`, `\r`, and `\n` characters. You may not use a custom header name that begins with `X-Bz-`.
*   `targetType` (required, string):
    Configuration type of the Event Notification rule. Currently, the only supported `targetType` is `"webhook"`.
*   `url` (required, string):
    The URL that identifies where the webhook resides. The URL must include the protocol, which must be HTTPS. The URL must not point to a Backblaze hostname or IP address.
*   `hmacSha256SigningSecret` (optional, string):
    This attribute specifies a 32-character secret that is used to sign the webhook invocation payload using the HMAC (Hash-based Message Authentication Code) SHA-256 algorithm. This alphanumeric string can include characters from 0-9 and A-Z, both uppercase and lowercase. The signing secret is encrypted at rest on Backblaze servers. The signature in the `X-Bz-Event-Notification-Signature` HTTP header of each Event Notification message is computed from `hmacSha256SigningSecret`, and it can be used to verify that the webhook originated from Backblaze. If this attribute is not set, then the webhook will not be signed.
    *(Note: This describes the secret stored by B2. When *setting* rules, you provide a `signingSecret` object containing `secretName` and `secretValue`.)*
*   `isSuspended` (optional, boolean):
    This attribute specifies whether the Event Notification rule is suspended. The value can be either `true` or `false`. By default, the value is `false`, meaning that the rule is not suspended. Backblaze may take action to suspend an Event Notification rule as necessary, based on operational policies. If Backblaze takes such action, the `suspensionReason` includes a brief description about why the rule was suspended. In such cases, the rule cannot be used until it is deleted and re-added (with appropriate updates), or if Backblaze resumes the rule. If you attempt to set this attribute yourself, it will be ignored.
*   `maxEventsPerBatch` (optional, integer):
    This attribute represents the maximum number of events a user will receive per webhook invocation. The value must be a number between 1 and 50. The default value is 1.
*   `suspensionReason` (optional, string):
    This attribute gives a brief description about why a rule was suspended. If present, this is a string. If you attempt to set this attribute yourself, it will be ignored. See the `isSuspended` attribute for more details.

## Event Types

Backblaze B2 currently supports the following event types for Event Notifications. New event types may be added in the future, so ensure that your code can handle the potential addition of new event types.

*   `b2:ObjectCreated:Upload`: A new object that is uploaded to Backblaze B2 that is not copied or replicated. This does not include multipart objects.
*   `b2:ObjectCreated:MultipartUpload`: A multipart object that was completed in Backblaze B2 that was not replicated.
*   `b2:ObjectCreated:Copy`: A copied object in Backblaze B2.
*   `b2:ObjectCreated:Replica`: An object that was replicated in Backblaze B2. This does not include multipart objects. This is the replicated object, and not the source object.
*   `b2:ObjectCreated:MultipartReplica`: A multipart object that was replicated in Backblaze B2. This is the replicated object, and not the source object.
*   `b2:ObjectDeleted:Delete`: An object that was deleted by user action, such as with an API call or by using the Backblaze web console.
*   `b2:ObjectDeleted:LifecycleRule`: An object that was deleted by a Lifecycle Rule.
*   `b2:HideMarkerCreated:Hide`: A hide marker that was created by user action, such as with an API call.
*   `b2:HideMarkerCreated:LifecycleRule`: A hide marker that was created by a Lifecycle Rule.
*   `b2:MultipartUploadCreated:LiveRead`: A multipart upload that was started from the S3-Compatible API with Live Read enabled.

Event types support the wildcard `*` only in the final component. For example, `b2:ObjectCreated:*` corresponds to:
*   `b2:ObjectCreated:Upload`
*   `b2:ObjectCreated:MultipartUpload`
*   `b2:ObjectCreated:Copy`
*   `b2:ObjectCreated:Replica`
*   `b2:ObjectCreated:MultipartReplica`

The wildcard also matches any new event types within the same category that you may add in the future.

An Event Notification rule must not specify any event types that overlap. For example, if both `b2:ObjectCreated:Upload` and `b2:ObjectCreated:*` are event types in the same Event Notification rule, it constitutes an error.

### Example Request Structure for `b2_set_bucket_notification_rules`

```json
{
  "bucketId": "aea8c5bc362ae55070130333",
  "eventNotificationRules": [
    {
      "eventTypes": [
        "b2:ObjectCreated:Upload",
        "b2:ObjectCreated:MultipartUpload"
      ],
      "isEnabled": true,
      "name": "mySampleRule1",
      "objectNamePrefix": "",
      "targetConfiguration": {
        "customHeaders": [
          {
            "name": "X-My-Custom-Header-1",
            "value": "myCustomHeaderVal1"
          },
          {
            "name": "X-My-Custom-Header-2",
            "value": "myCustomHeaderVal2"
          }
        ],
        "hmacSha256SigningSecret": "MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0", // This seems to be what B2 might return.
                                                                // For setting, use signingSecret object.
        "targetType": "webhook",
        "url": "https://www.example.com/sampleurl"
      }
    }
  ]
}
```
*(Note: The `hmacSha256SigningSecret` field shown here is likely what `b2_get_bucket_notification_rules` returns. When setting rules via `b2_set_bucket_notification_rules` or `b2_update_bucket`, you would use a `signingSecret` object: `{"signingSecret": {"secretName": "...", "secretValue": "..."}}` inside `targetConfiguration` if providing your own secret.)*


### Example Response Structure from an Event Notification Rule
*(Likely from `b2_get_bucket_notification_rules`)*

```json
{
  "bucketId": "aea8c5bc362ae55070130333",
  "eventNotificationRules": [
    {
      "eventTypes": [
        "b2:ObjectCreated:Upload",
        "b2:ObjectCreated:MultipartUpload"
      ],
      "isEnabled": true,
      "isSuspended": false,
      "name": "mySampleRule1",
      "objectNamePrefix": "",
      "suspensionReason": "",
      "targetConfiguration": {
        "customHeaders": [
          {
            "name": "X-My-Custom-Header-1",
            "value": "myCustomHeaderVal1"
          },
          {
            "name": "X-My-Custom-Header-2",
            "value": "myCustomHeaderVal2"
          }
        ],
        "hmacSha256SigningSecret": "MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0",
        "targetType": "webhook",
        "url": "https://www.example.com/sampleurl"
      }
    }
  ]
}
```

### Event Type Categories

An event type category is the event type without the final component. For example, the category for the event type `b2:ObjectCreated:Copy` is `b2:ObjectCreated`. The three event type categories are:

*   `b2:ObjectCreated`
*   `b2:ObjectDeleted`
*   `b2:HideMarkerCreated`

It is possible to use event types from different categories in the same Event Notification rule. For example, you could use both the event types `b2:ObjectCreated:Copy` and `b2:HideMarkerCreated:Hide` in the same rule. Additionally, you can make a rule that uses event types from the same category. For example, you could use both event types `b2:ObjectCreated:Copy` and `b2:ObjectCreated:Replica` in the same rule.

## Webhooks

Event Notifications are designed with an at-least-once delivery guarantee to ensure reliable delivery, even in the presence of network or system failures.

When an event that matches an Event Notification rule occurs within a bucket, Backblaze B2 sends a webhook (an HTTP POST request with a JSON-encoded payload) to the endpoint URL that you specify in the rule.

Backblaze B2 sets a three-second timeout on the webhook request. Your code should defer any substantial processing until after sending a 200 response to reply within the time limit. Backblaze B2 will retry the request if your endpoint does not return a 200 response within the time limit.

If the rule has an `hmacSha256SigningSecret` (meaning you configured one via the `signingSecret` object), each webhook invocation includes an `X-Bz-Event-Notification-Signature` HTTP header. The value of this header is the lowercase hex-encoded HMAC SHA-256 signature of the request payload, signed using the `secretValue` you provided in the Event Notification rule. You can use the header and value to ensure that the webhook invocation is coming from Backblaze. The signature value is prepended by the version number.

Example signature value: `v1=2c86b8e1f15f41f805f3331f3cf4eb20875be8887ab734b2cdccfa2350e5e231`.

Additionally, any custom HTTP headers that were defined in the Event Notification rules are included in the webhook requests.

### Example Webhook HTTP Request

```http
POST /sampleurl HTTP/1.1
Host: www.example.com
Content-Length: 468
X-Bz-Event-Notification-Signature: v1=2c86b8e1f15f41f8...
X-My-Custom-Header-1: myCustomHeaderVal1
X-My-Custom-Header-2: myCustomHeaderVal2
User-Agent: B2/EventNotifications
Content-Type: application/json; charset=UTF-8

{
  "events": [
    {
      "accountId": "e85c6a500333",
      "bucketId": "aea8c5bc362ae55070130333",
      "bucketName": "mySampleBucket",
      "eventId": "ba9a8e4eacda8b4b7d23a0ec1f04046342c319f3c608903e794c45a5b57184be",
      "eventTimestamp": 1684793309123,
      "eventType": "b2:ObjectCreated:Upload",
      "eventVersion": 1,
      "matchedRuleName": "mySampleRule1",
      "objectName": "objectName.txt",
      "objectSize": 10495842,
      "objectVersionId": "4_zaea8c5bc362a..."
    }
  ]
}
```

### Webhook JSON Payload Metadata Fields

*   `accountId`: The unique identifier of the account that owns the bucket where the object resides.
*   `bucketId`: The unique identifier of the bucket where the object resides.
*   `bucketName`: The name of the bucket where the object resides.
*   `eventId`: The unique identifier of the event.
*   `eventTimestamp`: The UTC time when this event was generated (milliseconds since epoch).
*   `eventType`: The event type of the Event Notification rule that corresponds to the event.
*   `eventVersion`: A numeric value indicating the version of the Event Notification payload.
*   `matchedRuleName`: The name of the Event Notification rule that corresponds to the event.
*   `objectName`: The name of the object that corresponds to the event.
*   `objectSize`: The size of the object in bytes (non-null on deletes; 0 for hide markers).
*   `objectVersionId`: The unique identifier for the version of the object.

### Verifying the Webhook Request Signature

If you provide an `hmacSha256SigningSecret` (via the `signingSecret` object with `secretName` and `secretValue` during rule creation), then the webhook request includes an `X-Bz-Event-Notification-Signature` HTTP header. The value is `v1=` followed by the lowercase hex-encoded HMAC SHA-256 signature of the request payload.

To verify:
1.  Use the `secretValue` (that your application stored when creating the rule) as the key.
2.  Use the raw request payload as the data.
3.  Compute an HMAC SHA-256 digest.
4.  Hex-encode the digest.
5.  Compare with the signature value from the header.

**Note:** Test events use the signing secret established during rule creation. The document provides a JavaScript example for verification, noting special handling for test events (though this might be outdated if test events are now properly signed with the configured secret).

### Application Key Capabilities

New application key capabilities for Event Notifications:

*   `readBucketNotifications`: Reads Event Notification rules. Used by `b2_get_bucket_notification_rules`.
*   `writeBucketNotifications`: Writes Event Notification rules. Used by `b2_set_bucket_notification_rules` (and implicitly by `b2_update_bucket` when modifying these rules). 