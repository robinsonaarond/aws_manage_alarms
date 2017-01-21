# aws_manage_alarms
For setting up classes of alerts.

The idea of this project was that the AWS Cloudwatch alarms make a reasonable analogue of Nagios for our AWS resources, but that it's a bit cumbersome getting all those alarms in.

This script currently finds each EC2, RDS, and Elasticache instance and automatically creates alarms for some of the metrics it finds.

Ideally you would edit this script to your taste.
