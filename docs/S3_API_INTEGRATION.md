# S3 API Integration for Accurate Bucket Size Reporting

This feature enhances bucket size reporting by using Backblaze B2's S3-compatible API to get more accurate storage statistics.

## Why Use the S3 API?

While the standard Backblaze B2 API provides good information about bucket contents, the S3-compatible API can sometimes provide more accurate and comprehensive size information, especially for:

1. Buckets with many files
2. Buckets with complex directory structures
3. Buckets containing multiple file versions
4. Optimized performance with large buckets

## How It Works

The S3 API integration:

1. Uses boto3 (the AWS SDK for Python) to connect to Backblaze B2's S3-compatible endpoint
2. Tries multiple regional endpoints as defined in [Backblaze S3-Compatible API Documentation](https://www.backblaze.com/docs/cloud-storage-call-the-s3-compatible-api)
3. Comprehensively lists all objects in each bucket
4. Calculates precise size information by processing each object individually
5. Caches results to minimize API calls and improve performance

## Supported Endpoints

As per Backblaze documentation, the S3 API endpoints follow this format:
```
https://s3.<region>.backblazeb2.com
```

The application will automatically try the following regions:
- US West (Phoenix AZ): `s3.us-west-004.backblazeb2.com`
- US West (Sacramento CA): `s3.us-west-001.backblazeb2.com` and `s3.us-west-002.backblazeb2.com`
- US East (Reston VA): `s3.us-east-005.backblazeb2.com`
- EU Central (Amsterdam NL): `s3.eu-central-003.backblazeb2.com`

## Key Requirements

For the S3 API integration to work, you need to:

1. **Use appropriate Backblaze B2 application keys**:
   - Create application keys with proper permissions
   - Avoid using keys with path restrictions
   - See the [S3-Compatible App Keys documentation](https://www.backblaze.com/docs/cloud-storage-s3-compatible-app-keys)

2. **Install required Python package**:
   ```
   pip install boto3
   ```

## Configuration

Enable S3 API integration by setting the following environment variable:

```
USE_S3_API=True
```

You can combine this with the accurate bucket size reporting option:

```
USE_ACCURATE_BUCKET_SIZE=True
USE_S3_API=True
```

## Authentication

The application uses the same B2 application key ID and key that you've configured for the standard API:

```
B2_APPLICATION_KEY_ID=your_key_id
B2_APPLICATION_KEY=your_application_key
```

## Best Practices

- **For Maximum Accuracy**: Enable both `USE_S3_API` and `USE_ACCURATE_BUCKET_SIZE`
- **For Balanced Performance**: Enable only `USE_ACCURATE_BUCKET_SIZE` 
- **For Maximum Performance**: Disable both options (`False`)
- **For S3 API Key Creation**: Use the Backblaze B2 console to create keys with "Read and Write" permissions and no path restrictions

## Performance Considerations

Using the S3 API may:
- Increase the time required to generate snapshots
- Consume more API calls (although Backblaze has generous free API call limits)
- Provide more accurate results for buckets with many objects or complex hierarchies

## Limitations

- The S3 API implementation respects Backblaze's recommendation for successive calls:
  - When uploading multiple versions of the same file, wait at least one second between uploads
  - When hiding a file, wait at least one second after uploading it
  - See [S3-Compatible API Documentation](https://www.backblaze.com/docs/cloud-storage-call-the-s3-compatible-api#successive-calls)

- The S3 API support is implemented using the boto3 library and supports all the operations documented by Backblaze
- Result in additional API calls to Backblaze B2
- Potentially increase your Backblaze transaction costs
- Use more memory for processing large buckets

## Troubleshooting

If you encounter issues with the S3 API integration:

1. Verify your Application Key has access to the S3 API
2. Check that the S3 endpoint is correct for your B2 storage region
3. Confirm that boto3 is properly installed
4. Review app logs for specific error messages

The system will automatically fall back to non-S3 methods if any issues occur with the S3 API.
