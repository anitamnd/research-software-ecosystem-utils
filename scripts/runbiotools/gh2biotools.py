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
HOST = 'http://bio-tools-dev.sdu.dk/'

def login(user, password):
    payload = {'username':user,'password':password}
    response = requests.post(HOST+'api/rest-auth/login/', headers=HEADERS, json=payload)
    token = response.json()['key']
    return token

def get_biotools_id_from_path(filepath):
    return os.path.splitext(os.path.basename(filepath))[0]


def delete_tool(token, biotools_id):
    headers = HEADERS.copy()
    headers['Authorization'] = f'Token {token}'
    tool_url = f'{HOST}/api/tool/{biotools_id}/'

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
    url = HOST + '/api/tool/validate/'

    tools_ok = []
    tools_ko = []
    tools_unchanged = []

    for biotools_json_file in files:
        try:
            logging.debug(f'uploading {biotools_json_file}...')
            payload_dict=json.load(open(biotools_json_file))

            payload_dict = remap(payload_dict, lambda p, k, v: k != 'term')

            # check if tool is already registered in bio.tools
            tool_id = payload_dict["biotoolsID"]
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
                    logging.debug(f'Tool {tool_id} already registered but changed')
                    # update the existing tool
                    response = requests.put(tool_url, headers=headers, json=payload_dict)
                    response.raise_for_status()
                    tools_ok.append(tool_id)
                    logging.debug(response.json())
                    logging.debug(f'done updating {biotools_json_file}')
                    continue
            elif response.status_code == 404:
                # tool not registered, proceed with upload
                logging.debug(f'Tool {tool_id} not registered, proceeding with upload')
                
                response = requests.post(url, headers=headers, json=payload_dict)
                response.raise_for_status()
                tools_ok.append(payload_dict["biotoolsID"])
                logging.debug(response.json())
                logging.debug(f'done uploading {biotools_json_file}')

        except requests.exceptions.HTTPError:
            if response.status_code == 500:
                soup = BeautifulSoup(response.text, "html.parser")
                messages = "; ".join([','.join(error_el.contents) for error_el in soup.find_all(class_='exception_value')])
            else:
                messages = response.text
            logging.error(f'error while uploading {biotools_json_file} (status {response.status_code}): {messages}')
            tools_ko.append(payload_dict["biotoolsID"])
        except:
            logging.error(f'error while uploading {biotools_json_file}', exc_info=True)
            tools_ko.append(payload_dict["biotoolsID"])

    logging.error('Tools upload finished')
    logging.error(f"Tools OK: {len(tools_ok)}")
    logging.error(f"Tools KO: {len(tools_ko)}")
    logging.error(f"Tools unchanged: {len(tools_unchanged)}")

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

    for deleted_file in args.deleted:
        biotools_id = get_biotools_id_from_path(deleted_file)
        logging.info(f"Deleting tool {biotools_id}...")
        delete_tool(args.token, biotools_id)
