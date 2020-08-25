#! /usr/bin/env python3

import argparse
import boto3
import sys
import json
from datetime import datetime
from datetime import timezone
import requests

# Handle arguments
parser = argparse.ArgumentParser(description='Send new AWS Health/PHD/Billing alerts to Slack')
parser.add_argument('-r', '--aws-region', default='us-east-1')
parser.add_argument('-p', '--profile-name')
parser.add_argument('-c', '--slack-channel')
args = parser.parse_args()

profile_name  = args.profile_name
region_name   = args.aws_region
slack_channel = args.slack_channel

state_file = '/tmp/aws_health_state_%s.json' % profile_name

def post_to_slack(msg, channel_webhook = slack_channel):
    try:
        print("Posting to %s" % channel_webhook)
        headers = { 'Content-type' : 'application/json', 'Accept' : 'text/plain' }
        r = requests.post(channel_webhook, data=json.dumps({"text":msg,"icon_emoji":"ghost"}), headers=headers)
    except Exception as e:
        print(e)

if __name__ == '__main__':
    # Get state file
    try:
        with open(state_file) as infile:
            state = json.load(infile)
    except:
        state = { 'event_log': [] }

    session = boto3.Session(profile_name=profile_name)
    health  = session.client('health', region_name=region_name)
    events  = health.describe_events()

    for event in events['events']:
        if event['region'] == 'us-west-2':
            event['startTime']       = event['startTime'].isoformat()
            event['endTime']         = event['endTime'].isoformat()
            event['lastUpdatedTime'] = event['lastUpdatedTime'].isoformat()

            # Ignore closed cases.  This is meant to run hourly or so, so it should catch ephemeral events well enough
            if event['statusCode'] != "closed":
                if event in state['event_log']:
                    print("Object already exists in state file.")
                else:
                    pdb_url = "<https://phd.aws.amazon.com/phd/home?region=%s#/dashboard/scheduled-changes?eventID=%s&eventTab=affectedResources&layout=vertical|Personal Health Dashboard>" % (event['region'], event['arn'])
                    msg = "Event: Account '%s', Type '%s', Status '%s', Code '%s'.  URL: %s" % (profile_name, event['eventTypeCategory'], event['statusCode'], event['eventTypeCode'], pdb_url)
                    post_to_slack(msg, slack_channel)
                    print("Adding object to state file.")
                    state['event_log'].append(event)

    # Re-press in state log file entries
    with open(state_file, 'w') as outfile:
        json.dump(state, outfile)

