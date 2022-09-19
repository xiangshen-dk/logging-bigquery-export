
This repo provides a solution for the '[mismatches in schema](https://cloud.google.com/logging/docs/export/bigquery#mismatch)' problem when exporting logs from Google Cloud Logging to BigQuery.

## Before you start

Make sure you have [configured the log sink](https://cloud.google.com/logging/docs/export/configure_export_v2) to BigQuery.

### Enable services
```bash
gcloud services enable run.googleapis.com \
    cloudscheduler.googleapis.com \
    cloudbuild.googleapis.com \
    compute.googleapis.com \
    containerregistry.googleapis.com
```

## Implementation steps

### Set the variables

Run the following commands. Change the service name and region if needed.
```bash
# Set your BigQuery dataset 
LOG_DATASET=[Your BQ DATASET]
# Set your table prefix. For examle schwab_log for table name schwab_log_(x)
TABLE_PREFIX=[Your BQ TABLE_PREFIX]
```
``` bash
SERVICE=schwab-log
REGION=us-east4
PROJECT=$(gcloud config get-value project)
CONTAINER="gcr.io/${PROJECT}/${SERVICE}"
PROJECT_NO=$(gcloud projects describe $PROJECT --format="value(projectNumber)")
SVC_ACCOUNT=${SERVICE}-service-account@${PROJECT}.iam.gserviceaccount.com
```

### Build docker image and deploy it to Cloud Run
1. Build and deploy the service
    ```bash
    gcloud builds submit --tag ${CONTAINER}
    gcloud run deploy ${SERVICE} \
        --image $CONTAINER \
        --platform managed \
        --no-allow-unauthenticated \
        --set-env-vars PROJECT=$PROJECT,LOG_DATASET=$LOG_DATASET,TABLE_PREFIX=$TABLE_PREFIX
    ```
1. Retrieve the service URL:
    ```bash
    SERVICE_URL=$(gcloud run services describe $SERVICE --region=$REGION --format='value(status.url)')
    ```

### Running the service on a schedule
1. Create the service account:
    ```bash
    gcloud iam service-accounts create \
        ${SERVICE}-service-account \
        --display-name "invoker-cloud-run-service-account"
    ```
1. For Cloud Run, give your service account permission to invoke your service:
    ```bash
    gcloud run services add-iam-policy-binding $SERVICE \
        --member=serviceAccount:${SVC_ACCOUNT} \
        --role=roles/run.invoker
    ```
1. Create the Cloud Scheduler job. The job runs every minite. You can change the schedule if needed.
    ```bash
    gcloud scheduler jobs create http log-run-job --schedule "* * * * *" \
        --http-method=POST \
        --uri=$SERVICE_URL \
        --location=$REGION \
        --oidc-service-account-email=$SVC_ACCOUNT \
        --oidc-token-audience=$SERVICE_URL
   ```
Read the [product doc](https://cloud.google.com/run/docs/triggering/using-scheduler) page for more details. It also provides Terraform examples.

### Verify the result

```json
{
    "Security": {
      "Vendor": "test"
    },
    "Actor": {
      "Cust": "*"
    },
    "Service": {
      "Operation": "authenticate",
      "URL": "/api/v2/web/authenticate?aid=test_web&clientId=CustomerWeb&sessionId=1234567&correlationId=12345abc",
      "CallType": "Rest",
      "Key": "sws_web.sws_login_1"
    },
    "Application": {
      "Host": "123.123.123.123",
      "APP_AppVersion": "5.2.3",
      "APP_ReqId": "c394c1b5-897f-4e0b-9c98-54b0f80e7d4e",
      "APP_Runtime": "AHC/2.1",
      "APP_AppName": "Transmit Auth",
      "APP_OS": "Linux"
    },
    "Results": {
      "ErrorCode": "0",
      "TraceLevel": "Information",
      "Message": "Success",
      "Elapsed": 0
    },
    "Extended_Fields": {
      "ElapsedMetrics": "*",
      "event": "*",
      "test_code": 500,
      "msg": "test"
    },
    "Header": {
      "AppId": "1863",
      "Ver": "5.2.3",
      "RecId": "9ca5a0b4-2a93-4c01-ae70-1744976c6edc",
      "Type": "Inbound",
      "SecureRefId": "9beb0086-bad6-4545-b293-15b00eb6de1e",
      "StartTS": "2022-02-21 13:51:58.602 +0000"
    }
  }
```

Set the input variable using the one-line format of the test json data:

```bash
input='{"Security":{"Vendor":"test"},"Actor":{"Cust":"*"},"Service":{"Operation":"authenticate","URL":"/api/v2/web/authenticate?aid=test_web&clientId=CustomerWeb&sessionId=1234567&correlationId=12345abc","CallType":"Rest","Key":"sws_web.sws_login_1"},"Application":{"Host":"123.123.123.123","APP_AppVersion":"5.2.3","APP_ReqId":"c394c1b5-897f-4e0b-9c98-54b0f80e7d4e","APP_Runtime":"AHC/2.1","APP_AppName":"Transmit Auth","APP_OS":"Linux"},"Results":{"ErrorCode":"0","TraceLevel":"Information","Message":"Success","Elapsed":0},"Extended_Fields":{"ElapsedMetrics":"*","event":"*","test_code":500,"msg":"test"},"Header":{"AppId":"1863","Ver":"5.2.3","RecId":"9ca5a0b4-2a93-4c01-ae70-1744976c6edc","Type":"Inbound","SecureRefId":"9beb0086-bad6-4545-b293-15b00eb6de1e","StartTS":"2022-02-21 13:51:58.602 +0000"}}'
```

Run the command to write Cloud Logging with the log name `schwab-log`:
```bash
gcloud logging write schwab-log $input --payload-type=json
```

Wait for a moment and run the following query:
```bash
bq query \
 --use_legacy_sql=false --format=prettyjson \
 "SELECT * FROM \`${PROJECT}.${LOG_DATASET}.${TABLE_PREFIX}*\` ORDER BY timestamp DESC LIMIT 1"
 ```
The initial result could take a minute or two. Re-run the query if needed. Once you have the query result, verify that the `test_code` under `extended_fields` has the value `500.0`.

Run the following command and you should receive a failure with a message `does not match any table`. That's because there is no schema mismatch yet.
 ```bash
bq query \
 --use_legacy_sql=false --format=prettyjson \
 "SELECT * FROM \`${PROJECT}.${LOG_DATASET}.export_errors_*\` ORDER BY timestamp DESC LIMIT 1"
 ```

Now, update the `test_code` from a number `500` to a string `code is 500` and try again:
```bash
input='{"Security":{"Vendor":"test"},"Actor":{"Cust":"*"},"Service":{"Operation":"authenticate","URL":"/api/v2/web/authenticate?aid=test_web&clientId=CustomerWeb&sessionId=1234567&correlationId=12345abc","CallType":"Rest","Key":"sws_web.sws_login_1"},"Application":{"Host":"123.123.123.123","APP_AppVersion":"5.2.3","APP_ReqId":"c394c1b5-897f-4e0b-9c98-54b0f80e7d4e","APP_Runtime":"AHC/2.1","APP_AppName":"Transmit Auth","APP_OS":"Linux"},"Results":{"ErrorCode":"0","TraceLevel":"Information","Message":"Success","Elapsed":0},"Extended_Fields":{"ElapsedMetrics":"*","event":"*","test_code":"code is 500","msg":"test"},"Header":{"AppId":"1863","Ver":"5.2.3","RecId":"9ca5a0b4-2a93-4c01-ae70-1744976c6edc","Type":"Inbound","SecureRefId":"9beb0086-bad6-4545-b293-15b00eb6de1e","StartTS":"2022-02-21 13:51:58.602 +0000"}}'
```

```bash
gcloud logging write schwab-log $input --payload-type=json
```

Run the following query and you should still see one record in the query result:
```bash
bq query \
 --use_legacy_sql=false --format=prettyjson \
 "SELECT * FROM \`${PROJECT}.${LOG_DATASET}.${TABLE_PREFIX}*\` ORDER BY timestamp DESC LIMIT 2"
 ```

Wait for a moment and run the following query:
 ```bash
bq query \
 --use_legacy_sql=false --format=prettyjson \
 "SELECT * FROM \`${PROJECT}.${LOG_DATASET}.export_errors_*\` ORDER BY timestamp DESC LIMIT 1"
 ```
The initial result could take a few minutes. Re-run the query if needed.

Once the query is successful, you should see a record in the error table.

By default, the scheduled job runs every minute and only processes the records in the past minute. Most likely, the first record is out of the window already. Therefore, you need to create one more log entry:

```bash
gcloud logging write schwab-log $input --payload-type=json
```

Wait for a minute for the scheduled job to run or manually invoke the scheduled job:
```base
gcloud scheduler jobs run log-run-job --location $REGION
```

Run the following command:
```bash
bq query \
 --use_legacy_sql=false --format=prettyjson \
 "SELECT * FROM \`${PROJECT}.${LOG_DATASET}.${TABLE_PREFIX}*\` ORDER BY timestamp DESC LIMIT 1"
 ```

Notice the field `jsonPayload` is `null` now and the new field `json_payload`  has the updated value. In case there is a delay, wait a little and re-run the command.

Also, run the query below and you can see the `test_code` has both the numeric and string value:

```bash
bq query \
 --use_legacy_sql=false --format=prettyjson \
 "SELECT json_payload['extended_fields']['test_code'] FROM \`${PROJECT}.${LOG_DATASET}.${TABLE_PREFIX}*\` ORDER BY timestamp DESC LIMIT 2"
 ```

 Sample output:
 ```console
 [
  {
    "f0_": "\"code is 500\""
  }, 
  {
    "f0_": null
  }
]
```

### Troubleshooting

If there is any issue, you can try to set the debug level to `DEBUG` in 
[main.py](./main.py). 

Save the file, build and deploy again:
```bash
gcloud builds submit --tag ${CONTAINER}

gcloud run deploy ${SERVICE} \
    --image $CONTAINER \
    --platform managed \
    --no-allow-unauthenticated \
    --set-env-vars PROJECT=$PROJECT,LOG_DATASET=$LOG_DATASET,TABLE_PREFIX=$TABLE_PREFIX
```

You should see the debug logs in Cloud Logging.