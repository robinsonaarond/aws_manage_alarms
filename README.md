# aws_manage_alarms
For setting up classes of alerts in AWS.

The idea of this project was that the AWS Cloudwatch alarms make a reasonable analogue of Nagios for our AWS resources, but that it's a bit cumbersome getting all those alarms in.

This script currently finds each EC2, RDS, and Elasticache instance and automatically creates alarms for some of the metrics it finds.  The alarms are based on pre-defined metrics baked into the script.  It also checks current alarms and doesn't try to re-create them if they exist.

This script depends on Boto and you having your AWS credentials in ~/.aws/credentials

Example command:
```aws_manage_alarms.py --profile "<aws_profile>" -r "<region>" -s "<sns_Topic_arn>"```
