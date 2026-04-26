""" config.ini 파일 로딩 파일"""

import configparser, os

def load_config(section: str, key: str):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base_dir, "config.ini")
    config = configparser.ConfigParser()
    config.read(path)

    return config[section][key].replace('"', '')
    
