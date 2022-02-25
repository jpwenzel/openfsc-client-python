#!/usr/bin/env bash

pipenv install --deploy

pipenv run python3 openfsc-client/openfsc-client.py
