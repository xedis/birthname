#! /bin/python3
import os
import hashlib
import argparse
import datetime
import logging
import multiprocessing
import json
import subprocess
import cv2
import numpy as np

# Setup argument parser
parser = argparse.ArgumentParser(description='Process some files.')
parser.add_argument('--dir', type=str, help='The directory to be processed')
parser.add_argument('--ext', type=str, help='The file extension to be processed')
parser.add_argument('--hash', type=str, default='sha256', choices=['sha256', 'sha1', 'md5', 'imagehash'], help='The hashing method to be used')
args = parser.parse_args()

# Ensure arguments are provided
if not args.dir or not args.ext:
    print("You must provide --dir and --ext arguments.")
    exit(1)

# Setup logging
logging.basicConfig(filename='file_renamer.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def calculate_hash(filename, method='sha256', block_size=65536):
    if method in ['sha256', 'sha1', 'md5']:
        if method == 'sha256':
            hasher = hashlib.sha256()
        elif method == 'sha1':
            hasher = hashlib.sha1()
        else:
            hasher = hashlib.md5()

        with open(filename, 'rb') as f:
            for block in iter(lambda: f.read(block_size), b''):
                hasher.update(block)
        return hasher.hexdigest()
    elif method == 'imagehash':
        # Using average hashing (aHash) from OpenCV
        image = cv2.imread(filename)
        resized = cv2.resize(image, (8, 8), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        avg = gray.mean()
        _, binary = cv2.threshold(gray, avg, 255, 0)
        # Convert binary image to hex string
        return ''.join(f'{i:02x}' for i in binary.flatten())

def get_creation_time_with_stat(filepath):
    try:
        # Use the stat command to get the birth time
        result = subprocess.run(['stat', '-c', '%W', filepath], capture_output=True, text=True, check=True)
        # The output will be the birth time in seconds since the Epoch
        birth_time_epoch = int(result.stdout.strip())
        if birth_time_epoch > 0:
            return birth_time_epoch
        else:
            return None
    except subprocess.CalledProcessError as e:
        print(f"Failed to get birth time for {filepath}: {e}")
        return None

def get_oldest_time(filepath):
    stats = os.stat(filepath)
    times = [stats.st_mtime, stats.st_ctime]
    birth_time_epoch = get_creation_time_with_stat(filepath)
    if birth_time_epoch:
        times.append(birth_time_epoch)
        logging.info(f"Birth time (creation time) for {filepath} obtained via stat command: {datetime.datetime.fromtimestamp(birth_time_epoch)}")
    else:
        logging.info(f"Using earliest of mtime or ctime for {filepath} as birth time could not be obtained.")
    oldest_time = min(times)
    logging.info(f"Oldest time used for {filepath}: {datetime.datetime.fromtimestamp(oldest_time)}")
    return oldest_time

def rename_file(file_info):
    directory, filename, extension, special_strings, hash_method = file_info
    old_name = os.path.join(directory, filename)
    oldest_time = get_oldest_time(old_name)
    date_string = datetime.datetime.fromtimestamp(oldest_time).strftime('%Y%m%d.%H%M%S')
    filehash = calculate_hash(old_name, hash_method)
    special_string = [s for s in special_strings if s in filename]
    special_string = '-' + special_string[0] if special_string else ''
    
    # Adjust filename format based on hashing method
    if hash_method == 'imagehash':
        # For imagehash: hash first, then timestamp
        new_name = os.path.join(directory, filehash + '-' + date_string + special_string + extension)
    else:
        # For other methods: timestamp first, then hash
        new_name = os.path.join(directory, date_string + '-' + filehash + special_string + extension)

    if old_name != new_name:  # Skip if the new name is the same as the old name
        base_new_name = new_name
        i = 1
        while os.path.exists(new_name):
            # Adjust increment placement based on hashing method
            if hash_method == 'imagehash':
                new_name = os.path.join(directory, filehash + '-' + date_string + special_string + '-' + str(i) + extension)
            else:
                new_name = base_new_name + '-' + str(i) + extension
            i += 1
        os.rename(old_name, new_name)
        logging.info(f'Renamed file {old_name} to {new_name}')
        return (old_name, new_name)
    else:
        logging.info(f'Skipped file {old_name} as it already has the correct name')
        return None

def undo_last_rename():
    try:
        with open('rename_history.json', 'r') as f:
            history = json.load(f)
        last_batch = history.pop()
        for old_name, new_name in last_batch.items():
            os.rename(new_name, old_name)
            logging.info(f'Reverted rename: {new_name} back to {old_name}')
        with open('rename_history.json', 'w') as f:
            json.dump(history, f)
    except Exception as e:
        logging.error(f"Error undoing last rename: {e}")

def rename_files(directory, extension):
    special_strings = ['before-color-correction', 'before-highres-fix', 'mask', 'before-refiner', 'mask-composite', 'censored', 'before-hires','before-face-restore', 'init-image']
    file_list = []
    for foldername, subfolders, filenames in os.walk(directory):
        for filename in filenames:
            if filename.endswith(extension):
                file_list.append((foldername, filename, extension, special_strings, args.hash))

    with multiprocessing.Pool() as pool:
        results = pool.map(rename_file, file_list)

    # Filter out None results before unpacking
    filtered_results = [result for result in results if result is not None]

    # Save rename history for undo feature
    rename_history = {old: new for old, new in filtered_results}
    if rename_history:
        try:
            with open('/var/log/rename_history.json', 'r') as f:
                history = json.load(f)
        except FileNotFoundError:
            history = []
        history.append(rename_history)
        with open('/var/log/rename_history.json', 'w') as f:
            json.dump(history, f)

if __name__ == "__main__":
    if args.dir == "undo":
        undo_last_rename()
    else:
        rename_files(args.dir, args.ext)
