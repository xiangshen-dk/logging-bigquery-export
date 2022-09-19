from flask import Flask
from google.cloud import bigquery
from datetime import datetime
import os
import json
import traceback
import logging

app = Flask(__name__)
client = bigquery.Client()

logging.basicConfig(level=logging.WARNING)
# logging.basicConfig(level=logging.DEBUG)

project_id = os.environ.get('PROJECT')
dataset = os.environ.get('LOG_DATASET')
frequency_in_min = os.environ.get('FREQUENCY_IN_MINUTES', 1)
table_prefix = os.environ.get('TABLE_PREFIX')
today = datetime.utcnow().date()
year_month_day = today.strftime("%Y%m%d")

log_table = f'{project_id}.{dataset}.{table_prefix}_{year_month_day}'
err_table = f'{project_id}.{dataset}.export_errors_{year_month_day}'
added_field_column_name = 'json_payload'


@app.route('/', methods=['POST'])
def index():
    try:
        add_extended_field_to_schema()
        all_rows_to_insert = []
        for row in get_error_data():
            log_entry = row.get('logEntry')
            logging.debug(f"log entry is: {log_entry}")

            log_json = json.loads(log_entry)
            json_payload = clean_up_keys(log_json['jsonPayload'])
            logging.debug(f"json payload: {json_payload}")

            log_json[added_field_column_name] = json.dumps(json_payload)
            logging.debug(f"{added_field_column_name}: {json_payload}")

            del (log_json['jsonPayload'])
            logging.debug(f"update log entry is: {log_json}")

            all_rows_to_insert.append(log_json)
        if all_rows_to_insert:
            row_ids = [x['insertId'] for x in all_rows_to_insert]
            # use row ids to avoid duplicates
            errors = client.insert_rows_json(
                log_table, all_rows_to_insert, row_ids)
            if errors:
                logging.error(
                    f"Encountered errors while inserting rows: {errors}")
            else:
                logging.info(
                    f"{len(all_rows_to_insert)} rows have been added.")
    except Exception as e:
        logging.error(e, traceback.print_exc())
    return "ok", 200


def clean_up_keys(d):
    # transform all invalid JSON keys for BigQuery
    if isinstance(d, dict):
        return {k.lower().replace('-', '_').replace('.', '_').replace('/', '_'): clean_up_keys(v) for k, v in d.items()}
    else:
        return d


def get_error_data():
    # add 5 seconds in case scheduler job is slightly off
    query = f'SELECT logEntry FROM {err_table} WHERE timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(),INTERVAL {frequency_in_min*60+5} SECOND)'
    query_job = client.query(query)
    return query_job.result()


def add_extended_field_to_schema():
    table = client.get_table(log_table)
    original_schema = table.schema

    added_json_field = bigquery.SchemaField(
        added_field_column_name, "JSON")
    if added_json_field in original_schema:
        logging.debug(f'{added_field_column_name} already exists.')
    else:
        new_schema = original_schema[:]
        new_schema.append(added_json_field)
        table.schema = new_schema
        table = client.update_table(table, ["schema"])

        if len(table.schema) == len(original_schema) + 1 == len(new_schema):
            logging.info(
                f"A new column {added_field_column_name} has been added.")
        else:
            logging.info(
                f"The column {added_field_column_name} has not been added.")


if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
