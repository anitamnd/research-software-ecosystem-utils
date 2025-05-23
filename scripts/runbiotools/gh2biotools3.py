#!/usr/bin/env python3
from datetime import datetime
import glob
import json
import logging
import argparse
import os
import requests
from bs4 import BeautifulSoup
from boltons.iterutils import remap

HEADERS = {'Content-Type': 'application/json', 'Accept': 'application/json'}
HOST = 'https://bio-tools-dev.sdu.dk'
TOOL_API_URL = f'{HOST}/api/tool/'
VALIDATE_API_URL = f'{HOST}/api/tool/validate/'

GITHUB_SHA = os.getenv('GITHUB_SHA', 'unknown')
logging.basicConfig(level=logging.INFO)   

def validate_tool(tool, token):
    '''Validate a tool using the bio.tools API.'''
    url = f'{HOST}/api/tool/validate/'
    headers = HEADERS.copy()
    headers['Authorization'] = f'Token {token}'

    r = requests.post(url, headers=headers, data=json.dumps(tool))
    if r.ok:
        return (True, r.text)
    return (False, r.text)


def upload_tool(tool, token):
    '''Upload a tool using the bio.tools API.'''
    headers = HEADERS.copy()
    headers['Authorization'] = f'Token {token}'
    url = TOOL_API_URL

    try:
        response = requests.post(url, headers=headers, data=json.dumps(tool))
        logging.info(f"{tool['biotoolsID']} added (Status: {response.status_code})")
        return True, response.text
    except requests.exceptions.HTTPError as e:
        logging.error(f"Error uploading {tool['biotoolsID']}: {e.response.status_code} {e.response.text}")
        return False, e.response.text
    except requests.exceptions.RequestException as e:
        logging.error(f"Error uploading {tool['biotoolsID']}: {e}")
        return False, str(e)


def update_tool(tool, token):
    """Updates an existing tool on bio.tools."""
    headers = HEADERS.copy()
    headers['Authorization'] = f'Token {token}'
    tool_url = f"{TOOL_API_URL}{tool['biotoolsID']}/"

    try:
        response = requests.put(tool_url, headers=headers, data=json.dumps(tool))
        logging.info(f"{tool['biotoolsID']} updated (Status: {response.status_code})")
        return True, response.text
    except requests.exceptions.HTTPError as e:
        logging.error(f"Error updating {tool['biotoolsID']}: {e.response.status_code} {e.response.text}")
        return False, e.response.text
    except requests.exceptions.RequestException as e:
        logging.error(f"Error updating {tool['biotoolsID']}: {e}")
        return False, str(e)


def delete_tool(token, biotools_id):
    '''Delete a tool using the bio.tools API'''
    headers = HEADERS.copy()
    headers['Authorization'] = f'Token {token}'
    tool_url = f'{TOOL_API_URL}{biotools_id}/'

    response = requests.delete(tool_url, headers=headers)

    if response.status_code == 204:
        logging.info(f"Successfully deleted tool {biotools_id}")
    elif response.status_code == 404:
        logging.warning(f"Tool {biotools_id} not found on server (maybe already deleted?)")
    else:
        logging.error(f"Failed to delete tool {biotools_id}: {response.status_code} {response.text}")


def run_upload(token, files):
    headers = HEADERS
    headers.update({'Authorization':f'Token {token}'})

    tools_ok = []
    tools_ko = []
    tools_unchanged = []

    for biotools_json_file in files:
        try:
            logging.debug(f'uploading {biotools_json_file}...')
            payload_dict=json.load(open(biotools_json_file))

            payload_dict = remap(payload_dict, lambda p, k, v: k != 'term')

            tool_id = payload_dict.get("biotoolsID")
            if not tool_id:
                logging.error(f"'biotoolsID' not found in {biotools_json_file}")
                tools_ko.append(("UNKNOWN", "biotoolsID not found"))
                continue

            tool_url = HOST + '/api/tool/' + tool_id + '/'
            response = requests.get(tool_url, headers=headers)

            if response.status_code == 200:
                # compare json of existing tool with the one to be uploaded
                existing_tool = response.json()
                existing_tool = remap(existing_tool, lambda p, k, v: k != 'term')
                if existing_tool == payload_dict:
                    logging.debug(f'Tool {tool_id} already registered and unchanged')
                    tools_unchanged.append(tool_id)
                    continue
                else:
                    # update the existing tool
                    logging.info(f'Tool {tool_id} already registered but changed, attempting update...')
                    success, message = update_tool(payload_dict, token)
                    if success:
                        tools_ok.append(tool_id)
                    else:
                        tools_ko.append((tool_id, message))
                        logging.error(f"Update failed for {tool_id}: {message}")
                      
            elif response.status_code == 404:
                # tool not registered, proceed with upload
                logging.info(f'Tool {tool_id} not registered, proceeding with upload')                    
                valid, validation_message = validate_tool(payload_dict, token)
                if valid:
                    success, upload_message = upload_tool(payload_dict, token)
                    if success:
                        tools_ok.append(tool_id)
                    else:
                        tools_ko.append((tool_id, upload_message))
                        logging.error(f"Upload failed for {tool_id}: {upload_message}")
                else:
                    tools_ko.append((tool_id, validation_message))
                    logging.error(f"Validation failed for {tool_id}: {validation_message}")

            else:
                logging.error(f"Error checking tool {tool_id}: {response.status_code} {response.text}")
                tools_ko.append((tool_id, response.text))

        except requests.exceptions.HTTPError:
            if response.status_code == 500:
                soup = BeautifulSoup(response.text, "html.parser")
                messages = "; ".join([','.join(error_el.contents) for error_el in soup.find_all(class_='exception_value')])
            else:
                messages = response.text
            logging.error(f'error while uploading {biotools_json_file} (status {response.status_code}): {messages}')
            tools_ko.append((payload_dict["biotoolsID"], messages))
        except Exception as e:
            logging.error(f"Unexpected error with {biotools_json_file}: {str(e)}", exc_info=True)
            tools_ko.append((payload_dict["biotoolsID"], str(e)))


    logging.info('Tools upload finished')
    logging.info(f"Tools OK: {len(tools_ok)}")
    logging.info(f"Tools KO: {len(tools_ko)}")
    logging.info(f"Tools unchanged: {len(tools_unchanged)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Sync changed and deleted .biotools.json files with bio.tools server')

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

    if tools_ko:
        with open("upload_failure_report.txt", "w") as report:
            report.write("🚨 The following tools failed to upload, update, or delete:\n\n")
            for tool_id, error_msg in tools_ko:
                short_msg = error_msg.strip().replace('\n', ' ')[:300]  # limit and flatten
                report.write(f"- **{tool_id}**: {short_msg}\n")

            report.write("\n---\n")
            report.write(f"- 🔁 Git commit: `{GITHUB_SHA}`\n")
