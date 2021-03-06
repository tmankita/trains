import json
import os
import re
from PIL import Image
import yaml

import pandas as pd
from urllib.parse import urlparse
from dateutil.tz import tzutc
import datetime

def tag_parser(migrant, id, tag, value):
    if(tag.startswith("VALUETAG_")):
        migrant.info[id][migrant.tags]["VALUETAG"][tag.replace("VALUETAG_","")] = value
    else:
        migrant.info[id][migrant.tags][tag] = value


def source_name_parser(migrant):
    def f(id, value):
        index = value.rfind("/")
        if index > 0:
            entry_point = value[index + 1 :]
            working_dir = value[0:index]
        else:
            entry_point = working_dir = value
        migrant.info[id][migrant.tags]["working_dir"] = working_dir
        migrant.info[id][migrant.tags]["entry_point"] = entry_point

    return f


def log_model_history_tag_parser(migrant):
    # type: (Migrant) -> any
    """

    :param migrant: Migrant object
    :return:
    """

    def f(id, value):
        # type: (str,str) -> void
        """
        Store history log-model information

        Example:
        {
            "run_id": "ddf851a16bb34af2a398539c10fd21bf",
            "artifact_path": "model",
            "utc_time_created": "2020-09-30 09:33:06.983478",
            "flavors":
                {
                    "tensorflow":
                        {
                            "saved_model_dir": "tfmodel",
                             "meta_graph_tags": ["serve"],
                              "signature_def_key": "predict"
                        },
                    "python_function":
                        {
                            "loader_module": "mlflow.tensorflow",
                             "python_version": "3.6.12",
                              "env": "conda.yaml"
                        }
                }
        }

        :param id: Expirament id
        :param value: json value
        """
        history = json.loads(value)
        migrant.info[id][migrant.tags]["log-model.history"] = history[0]

    return f


def epochs_summary_parser(migrant, id, path_tree, tag, lines):
    metric = []
    iteration = 0
    for line in lines:
        parts = line.split(" ")
        score = parts[1] if len(parts) > 1 else parts[0]
        point = [iteration, score]
        metric.append(point)
        iteration += 1
    if path_tree[-1] == migrant.metrics:
        migrant.info[id][migrant.metrics].append((tag, tag, metric))
    elif len(path_tree) == 2:
        migrant.info[id][migrant.metrics].append((path_tree[-1], path_tree[-1], metric))
    else:
        migrant.info[id][migrant.metrics].append((path_tree[-2], path_tree[-1], metric))


def get_value_from_path(path):
    index = path.rfind("/")
    name = path[index + 1:]
    if "model" in name:
        return None
    elif "parquet" in name:
        if not ".parquet" in name:
            name, path = update_path(path)
        dataFrame = pd.read_parquet(path)
        return ("dataframe", name, dataFrame)
    elif "csv" in name:
        if not ".csv" in name:
            name, path = update_path(path)
        dataFrame = pd.read_csv(path)
        return ("dataframe", name, dataFrame)


def update_path(path):
    files = list(os.walk(path))[0][2]  # returns all the files in path
    for name in files:
        if re.match(r"^\.", name):
            continue
        if ".parquet" in name:
            return (name, path + os.sep + name)
        elif ".csv" in name:
            return (name, path + os.sep + name)


def get_all_artifact_files(migrant, id, path, is_http_migrant = False):
    if not os.path.isdir(path):
        return
    dirs = list(os.walk(path))[0][1]  # returns all the dirs in 'path'
    for dir in dirs:
        if "model" in dir:
            files = list(os.walk(path + os.sep + dir))[0][2]  # returns all the files in 'path'
            for name in files:
                if name.endswith(".yaml"):
                    with open(path + os.sep + dir + os.sep + name) as file:
                        documents = yaml.full_load(file)
                        migrant.info[id][migrant.artifacts]["requirements"] = str(documents)
                        break
            migrant.insert_artifact_by_type(id, "folder", dir, path + os.sep + dir)
        elif is_http_migrant:
            migrant.insert_artifact_by_type(id, "folder", dir, path + os.sep + dir)
    files = list(os.walk(path))[0][2]  # returns all the files in 'path'
    for file_name in files:
        if file_name.endswith(".json"):
            with open(path + os.sep + file_name) as json_file:
                data = json.load(json_file)
                migrant.insert_artifact_by_type(id, "dictionary", file_name, data)
        elif (
            file_name.endswith(".png")
            or file_name.endswith(".jpg")
            or file_name.endswith(".jpeg")
        ):
            im = Image.open(path + os.sep + file_name)
            migrant.insert_artifact_by_type(id, "image", file_name, im)
        elif file_name.endswith(".txt"):
            with open(path + os.sep + file_name) as txt_file:
                data = txt_file.read()
                migrant.insert_artifact_by_type(id, "text", file_name, data)


def __get_description(tag, value):
    return ""


def generate_train_param(value, tag):
    if re.match(r"^\d*\.\d+", value):
        value = {
            "section": "Args",
            "name": tag,
            "value": value,
            "type": "float",
            "description": __get_description(tag, value),
        }
    elif re.match(r"^\d+", value):
        value = {
            "section": "Args",
            "name": tag,
            "value": value,
            "type": "int",
            "description": __get_description(tag, value),
        }
    elif value == "True" or value == "False":
        value = {
            "section": "Args",
            "name": tag,
            "value": value,
            "type": "boolean",
            "description": __get_description(tag, value),
        }
    else:
        value = {
            "section": "Args",
            "name": tag,
            "value": value,
            "type": "string",
            "description": __get_description(tag, value),
        }
    return value


def insert_param(migrant, id, value, tag, is_http_migrant = False):
    if (not is_http_migrant) and re.match(r"^[Ff]ile://", value):
        p = urlparse(value)
        value = os.path.abspath(os.path.join(p.netloc, p.path))
        value = get_value_from_path(value)
        if value:
            migrant.insert_artifact(id, value)
    elif re.match(r"^[Hh]ttps?://", value):
        value = get_value_from_path(value)
        if value:
            migrant.insert_artifact(id, value)
    elif re.match(r"^(?:s3://)|(?:gs://)|(?:azure://)", value):
        parts = value.split('/')
        value = ("storage-server", parts[-1], value)
        migrant.insert_artifact(id, value)
    else:
        value = generate_train_param(value, tag)
        migrant.info[id][migrant.params][tag] = value


def parse_DateTime(start_time,end_time):
    timestamp_start_time = int(start_time) / 1000 if start_time else None
    timestamp_end_time = int(end_time) / 1000 if end_time else None
    data_time_start = (
        datetime.datetime.fromtimestamp(timestamp_start_time, tz=tzutc())
        if timestamp_start_time
        else None
    )
    data_time_end = (
        datetime.datetime.fromtimestamp(timestamp_end_time, tz=tzutc())
        if timestamp_end_time
        else None
    )
    return data_time_start, data_time_end