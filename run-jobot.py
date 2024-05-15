#!/usr/bin/env python3

import subprocess
import sys
import os
import requests
import json
import zipfile
from io import BytesIO

# Required packages
dependencies = ['requests']

for package in dependencies:
    try:
        __import__(package)
    except ImportError:
        print(f"Installing the '{package}' package...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])

# Version configuration for easy updates
MAINNET_VERSION = "v3.9.0"
DEVNET_VERSION = "v5.2.0"
TESTNET_VERSION = "v5.0.1"

# Mapping of environment to chain ID and version
ENV_TO_CONFIG = {
    "local": {"chain_id": None, "version": "latest"},
    "devnet": {"chain_id": "arctic-1", "version": DEVNET_VERSION},
    "testnet": {"chain_id": "atlantic-2", "version": TESTNET_VERSION},
    "mainnet": {"chain_id": "pacific-1", "version": MAINNET_VERSION}
}

def print_ascii_and_intro():
    print("""
                     ..:=++****++=:.
                  .:+*##############*+:.
                .=*#####+:....:+#######+.
              .-*#####=.  ....  .+###*:. ...
            ..+#####=.. .=####=.  .... .-*#=.
            .+#####+. .=########+:...:=*####=.
            =########*#######################-
           .#################=:...=###########.
           ...  ..-*######+..      .:*########:
            ..=-.   -###-    -####.   :+######:
           :#####+:       .=########:   .+####:
           .########+:.:=#############=-######.
            =################################-
            .+#####*-.. ..-########+.. ..-*#=.
            ..+##*-. ..... .-*###-. ...... ..
              .--. .:*###*:.  ...  .+###*-.
                 .:+#######*-:..::*#####=.
                  .-+###############*+:.
                     ..-+********+-.

Welcome to the Sei node installer!
For more information please visit docs.sei.io
Please make sure you have the following installed locally:
\t- golang 1.21 (with PATH and GOPATH set properly)
\t- make
\t- gcc
\t- docker
This tool will build from scratch seid and wipe away existing state.
Please backup any important existing data before proceeding.
""")

# interactive setup prompts #not using 
# def take_manual_inputs():
#     env = input("Choose an environment (1: local, 2: devnet, 3: testnet, 4: mainnet): ")
#     while env not in ['1', '2', '3', '4']:
#         print("Invalid input. Please enter '1', '2', '3', or '4'.")
#         env = input("Choose an environment: ")

#     env = ["local", "devnet", "testnet", "mainnet"][int(env) - 1]

#     # Change the default option for the database backend to "sei-db", which is option 2
#     db_choice = input("Choose the database backend (1: legacy, 2: sei-db [default]): ").strip() or "2"

#     return env, db_choice

def install_release(version):
    """
    Install a specific version of the release based on the given version tag.
    """
    try:
        # Download zip
        zip_url = f"https://github.com/sei-protocol/sei-chain/archive/refs/tags/{version}.zip"
        response = requests.get(zip_url)
        response.raise_for_status()
        zip_file = zipfile.ZipFile(BytesIO(response.content))
        zip_file.extractall(".")

        # Install
        os.chdir(zip_file.namelist()[0])
        subprocess.run("make install", shell=True, check=True)
        print("Successfully installed version:", version)

    except requests.exceptions.HTTPError as e:
        print(f"HTTP error occurred: {e}")  # handle http error
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"Error downloading files: {e}")  # handle other errors
        sys.exit(1)
    except zipfile.BadZipFile:
        print("Error unzipping file. The downloaded file may be corrupt.")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Installation failed during 'make install': {e}")
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        sys.exit(1)

def get_rpc_server(chain_id):
    chains_json_url = "https://raw.githubusercontent.com/sei-protocol/chain-registry/main/chains.json"
    response = requests.get(chains_json_url)
    if response.status_code != 200:
        print("Failed to retrieve chain information.")
        return None

    try:
        chains = response.json()
    except json.JSONDecodeError:
        print("JSON decoding failed")
        return None

    # fetch chain info by chain_id
    chain_info = chains.get(chain_id)
    if not chain_info:
        print("Chain ID not found in the registry.")
        return None

    # fetch and use first rpc that responds
    rpcs = chain_info.get('rpc', [])
    for rpc in rpcs:
        rpc_url = rpc.get('url')
        try:
            if requests.get(rpc_url).status_code == 200:
                return rpc_url
        except requests.RequestException as e:
            print(f"Failed to connect to RPC server {rpc_url}: {e}")
            continue  # try next url if current one fails

    return None

# fetch state sync params
def get_state_sync_params(rpc_url):
    trust_height_delta = 40000 # may need to tune
    response = requests.get(f"{rpc_url}/status")
    latest_height = int(response.json()['sync_info']['latest_block_height'])
    sync_block_height = latest_height - trust_height_delta if latest_height > trust_height_delta else latest_height
    response = requests.get(f"{rpc_url}/block?height={sync_block_height}")
    sync_block_hash = response.json()['block_id']['hash']
    return sync_block_height, sync_block_hash

# fetch peers list
def get_persistent_peers(rpc_url):
    with open(os.path.expanduser('~/.sei/config/node_key.json'), 'r') as f:
        self_id = json.load(f)['id']
        response = requests.get(f"{rpc_url}/net_info")
        peers = [peer['url'].replace('mconn://', '') for peer in response.json()['peers'] if peer['node_id'] != self_id]
        persistent_peers = ','.join(peers)
        return persistent_peers

# fetch and write genesis file directly from source
def write_genesis_file(chain_id):
    genesis_url = f"https://raw.githubusercontent.com/sei-protocol/testnet/main/{chain_id}/genesis.json"
    response = requests.get(genesis_url)
    if response.status_code == 200:
        genesis_path = os.path.expanduser('~/.sei/config/genesis.json')
        with open(genesis_path, 'wb') as file:
            file.write(response.content)
        print("Genesis file written successfully.")
    else:
        print(f"Failed to download genesis file: HTTP {response.status_code}")

def run_command(command):
    try:
        subprocess.run(command, shell=True, check=True)
        print(f"Command executed successfully: {command}")
    except subprocess.CalledProcessError as e:
        print(f"Failed to execute command '{command}': {e}")
        sys.exit(1)

def ensure_file_path(file_path):
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    if not os.path.exists(file_path):
        open(file_path, 'a').close()
        print(f"Created missing file: {file_path}")

# Main execution function
def main():
    print_ascii_and_intro()
    env = "mainnet"
    db_choice = "2"
    moniker = "jobot"
    print(f"Setting up a node in {env}")

    # Fetching chain_id from the ENV_TO_CONFIG using the selected environment
    config = ENV_TO_CONFIG[env]
    chain_id = config['chain_id']  # Ensuring chain_id is defined

    # Install the selected release based on environment
    install_release(config['version'])

    # Get RPC server URL or default to localhost for local environment
    rpc_url = get_rpc_server(chain_id) if chain_id else "http://localhost:26657"

    # Clean up previous data and initialize seid with the given chain ID and moniker
    subprocess.run(f"rm -rf $HOME/.sei && seid init {moniker} --chain-id {chain_id}", shell=True, check=True)

    # Fetch synchronization parameters and persistent peers
    sync_block_height, sync_block_hash = get_state_sync_params(rpc_url)
    persistent_peers = get_persistent_peers(rpc_url)

    # Fetch and write genesis
    write_genesis_file(chain_id)

    # Configuration settings
    config_path = os.path.expanduser('~/.sei/config/config.toml')
    app_config_path = os.path.expanduser('~/.sei/config/app.toml')

    # confirm  exists before modifying config files
    ensure_file_path(config_path)
    ensure_file_path(app_config_path)

    # Read and modify config.toml
    with open(config_path, 'r') as file:
        config_data = file.read()
        config_data = config_data.replace('rpc-servers = ""', f'rpc-servers = "{rpc_url},{rpc_url}"')
        config_data = config_data.replace('trust-height = 0', f'trust-height = {sync_block_height}')
        config_data = config_data.replace('trust-hash = ""', f'trust-hash = "{sync_block_hash}"')
        config_data = config_data.replace('persistent-peers = ""', f'persistent-peers = "{persistent_peers}"')
        config_data = config_data.replace('enable = false', 'enable = true')
        config_data = config_data.replace('db-sync-enable = true', 'db-sync-enable = false')
        config_data = config_data.replace('use-p2p = false', 'use-p2p = true')
    with open(config_path, 'w') as file:
        file.write(config_data)

    # Read, modify, and write app.toml if sei-db is selected
    if db_choice == "1":
        with open(app_config_path, 'r') as file:
            app_data = file.read()
        app_data = app_data.replace('sc-enable = false', 'sc-enable = true')
        app_data = app_data.replace('ss-enable = false', 'ss-enable = true')
        with open(app_config_path, 'w') as file:
            file.write(app_data)

    # Start seid
    print("Starting seid...")
    run_command("seid start")


if __name__ == "__main__":
    main()
