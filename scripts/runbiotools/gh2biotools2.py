#!/usr/bin/env python3
from datetime import datetime
import glob
import json
import logging
import argparse
import os
import sys
import requests
from bs4 import BeautifulSoup
from boltons.iterutils import remap

HOST = 'https://bio-tools-dev.sdu.dk'
TOOL_API_URL = f'{HOST}/api/tool/'
HEADERS = {
    'Content-Type': 'application/json', 
    'Accept': 'application/json'
}

logging.basicConfig(level=logging.INFO)   


def get_headers(token):
    '''Get headers for the API requests.'''
    headers = HEADERS.copy()
    headers['Authorization'] = f'Token {token}'
    return headers


def validate_tool(tool, token):
    '''Validate a tool using the bio.tools API.'''
    url = f'{HOST}/api/tool/validate/'
    response = requests.post(url, headers=get_headers(token), data=json.dumps(tool))
    return response.ok, response.text


def upload_tool(tool, token):
    '''Upload a tool using the bio.tools API.'''
    try:
        response = requests.post(TOOL_API_URL, headers=get_headers(token), data=json.dumps(tool))
        logging.info(f"{tool['biotoolsID']} added (Status: {response.status_code})")
        return True, response.text
    except requests.exceptions.RequestException as e:
        logging.error(f"Error uploading {tool['biotoolsID']}: {e}")
        return False, str(e)


def update_tool(tool, token):
    """Updates an existing tool on bio.tools."""
    tool_url = f"{TOOL_API_URL}{tool['biotoolsID']}/"
    try:
        response = requests.put(tool_url, headers=get_headers(token), data=json.dumps(tool))
        logging.info(f"{tool['biotoolsID']} updated (Status: {response.status_code})")
        return True, response.text
    except requests.exceptions.RequestException as e:
        logging.error(f"Error updating {tool['biotoolsID']}: {e}")
        return False, str(e)


def delete_tool(token, biotools_id):
    '''Delete a tool using the bio.tools API'''
    tool_url = f'{TOOL_API_URL}{biotools_id}/'
    response = requests.delete(tool_url, headers=get_headers(token))

    if response.status_code == 204:
        logging.info(f"Successfully deleted tool {biotools_id}")
    elif response.status_code == 404:
        logging.warning(f"Tool {biotools_id} not found on server (maybe already deleted?)")
    else:
        logging.error(f"Failed to delete tool {biotools_id}: {response.status_code} {response.text}")


def run_upload(token, files):
    tools_ok = []
    tools_ko = []
    tools_unchanged = []

    for biotools_json_file in files:
        try:
            logging.debug(f'Processing {biotools_json_file}...')
            
            payload_dict = json.load(open(biotools_json_file))
            payload_dict = remap(payload_dict, lambda p, k, v: k != 'term')
            tool_id = payload_dict.get("biotoolsID")

            if not tool_id:
                logging.error(f"'biotoolsID' not found in {biotools_json_file}")
                tools_ko.append("UNKNOWN")
                continue

            tool_url = f'{HOST}/api/tool/{tool_id}/'
            response = requests.get(tool_url, headers=HEADERS)

            if response.status_code == 200:
                existing_tool = remap(response.json(), lambda p, k, v: k != 'term')
                if existing_tool == payload_dict:
                    logging.debug(f'Tool {tool_id} already registered and unchanged')
                    tools_unchanged.append(tool_id)

                else:
                    logging.info(f'Tool {tool_id} changed, attempting update...')
                    valid, msg = validate_tool(payload_dict, token)
                    if valid:
                        success, msg = update_tool(payload_dict, token)
                        if success:
                            tools_ok.append(tool_id)
                            logging.info(f"Tool {tool_id} updated successfully")
                        else:
                            tools_ko.append(tool_id)
                            logging.error(f"Update failed for {tool_id}: {msg}")
                    else:
                        tools_ko.append(tool_id)
                        logging.error(f"Validation failed for {tool_id}: {msg}")
            
            elif response.status_code == 404:
                # tool not registered, proceed with upload
                logging.info(f'Tool {tool_id} not registered, proceeding with upload')                    
                valid, msg = validate_tool(payload_dict, token)
                if valid:
                    success, msg = upload_tool(payload_dict, token)
                    if success:
                        tools_ok.append(tool_id)
                    else:
                        tools_ko.append(tool_id)
                        logging.error(f"Upload failed for {tool_id}: {msg}")
                else:
                    tools_ko.append(tool_id)
                    logging.error(f"Validation failed for {tool_id}: {msg}")

            else:
                logging.error(f"Error checking tool {tool_id}: {response.status_code} {response.text}")
                tools_ko.append(tool_id)


        except requests.exceptions.HTTPError:
            if response.status_code == 500:
                soup = BeautifulSoup(response.text, "html.parser")
                messages = "; ".join([','.join(error_el.contents) for error_el in soup.find_all(class_='exception_value')])
            else:
                messages = response.text

            logging.error(f'HTTP error for {biotools_json_file} (status {response.status_code}): {messages}')
            tools_ko.append(payload_dict.get("biotoolsID", "UNKNOWN"))

        except Exception as e:
            logging.error(f"Unexpected error with {biotools_json_file}: {str(e)}", exc_info=True)
            tools_ko.append(payload_dict.get("biotoolsID", "UNKNOWN"))


    logging.info('Summary:')
    logging.info(f"✅ Tools OK: {len(tools_ok)}: {tools_ok}")
    logging.info(f"❌ Failed: {len(tools_ko)}: {tools_ko}")
    logging.info(f"⚠️ Unchanged: {len(tools_unchanged)}: {tools_unchanged}")

    if tools_ko:
        sys.exit(1)



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Sync changes to .biotools.json files with bio.tools server')

    parser.add_argument('--token', type=str, help='bio.tools token')
    parser.add_argument('--files', metavar='F', type=str, nargs='+',
                        help='List of changed/created .biotools.json files to process')
    parser.add_argument('--deleted', metavar='D', type=str, nargs='*',
                        help='List of deleted .biotools.json files to remove from bio.tools')
    
    args = parser.parse_args()

    if args.files:
        run_upload(args.token, args.files)

    if args.deleted:
        for deleted_file in args.deleted:
            biotools_id = os.path.basename(deleted_file).split('.')[0]
            logging.info(f"Deleting tool {biotools_id}...")
            delete_tool(args.token, biotools_id)
