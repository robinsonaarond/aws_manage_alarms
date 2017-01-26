#! /usr/bin/env python
import argparse

import boto
import boto.ec2
import boto.ec2.cloudwatch
import boto.elasticache
import boto.rds
import sys
import time

# Handle arguments
parser = argparse.ArgumentParser(description='Automatically create alerts')
parser.add_argument('-p', '--profile-name', default='default')
parser.add_argument('-r', '--aws-region', default='us-west-2')
parser.add_argument('-s', '--sns-topic')
args = parser.parse_args()

profile_name = args.profile_name
region       = args.aws_region
sns_topic    = args.sns_topic

# Get list of instances
def get_ec2_instances(profile_name):
    ec2 = boto.ec2.connect_to_region(region,profile_name=profile_name)
    reservations = ec2.get_all_reservations()
    inst = []
    for reservation in reservations:
        for instance in reservation.instances:
            try:
                inst.append([instance.id, instance.tags['Name']])
            except:
                inst.append([instance.id])
    return inst

def get_elasticache_instances(profile_name):
    ec = boto.elasticache.connect_to_region(region,profile_name=profile_name)
    ec_clusters = []
    for cluster in ec.describe_cache_clusters().values()[0]['DescribeCacheClustersResult']['CacheClusters']:
        ec_clusters.append(str(cluster['CacheClusterId']))
    return ec_clusters

def get_rds_instances(profile_name):
    rds = boto.rds.connect_to_region(region,profile_name=profile_name)
    rds_instances = []
    for instance in rds.get_all_dbinstances():
        rds_instances.append(str(instance.id))
    return rds_instances

def apply_alarms(instance_id, cloudwatch_connection, instance_metrics, comparison=">=", threshold=1, period=300, evaluation_periods=2, statistic='Average', sns_topic=sns_topic, service_type = 'InstanceId', force=False):
    active_alarms = [ x.name for x in cloudwatch_connection.describe_alarms() ]
    if isinstance(instance_metrics, str):
        instance_metrics = [instance_metrics]
    if isinstance(instance_id, str):
        instance_id = [instance_id]

    for instance_metric in instance_metrics:
        if len(instance_id) > 1:
            instance_name = instance_id[1]
            metric_name = "%s-%s-%s" % (profile_name,instance_name,instance_metric)
            instance_id = instance_id[0]
        else:
            instance_id = instance_id[0]
            metric_name = "%s-%s-%s" % (profile_name,instance_id,instance_metric)

        if metric_name in active_alarms and not force:
            print "Metric %s is already configured" % metric_name
        else:
            metric = cloudwatch_connection.list_metrics(dimensions={service_type:instance_id}, metric_name=instance_metric)
            if len(metric) > 0:
                print "Creating metric for %s (%s): " % (instance_id,metric_name), metric[0]
                metric[0].create_alarm(name=metric_name,
                                       comparison=comparison,
                                       threshold=threshold,
                                       period=period,
                                       evaluation_periods=evaluation_periods,
                                       statistic=statistic,
                                       alarm_actions=[sns_topic])
                time.sleep(0.5)


if __name__ == '__main__':
    cw  = boto.ec2.cloudwatch.connect_to_region(region,profile_name=profile_name)

    # EC2 Instances
    # Note: DiskSpaceUtilization is a custom metric; you'd need to roll your own to get that.
    for instance_id in get_ec2_instances(profile_name):
        apply_alarms(instance_id, cw, "CPUCreditBalance", comparison="<=", threshold=50)
        apply_alarms(instance_id, cw, "StatusCheckFailed")
        apply_alarms(instance_id, cw, "MemoryUtilization", threshold=80)
        apply_alarms(instance_id, cw, "DiskSpaceUtilization", threshold=80)
    
    # Elasticache
    for cluster_instance in get_elasticache_instances(profile_name):
        apply_alarms(cluster_instance, cw, "SwapUsage", threshold=1000000000, service_type='CacheClusterId')
    
    # RDS
    for db_instance in get_rds_instances(profile_name):
        apply_alarms(db_instance, cw, "SwapUsage", threshold=1000000000, service_type='DBInstanceIdentifier')
        apply_alarms(db_instance, cw, "CPUCreditBalance", comparison="<=", threshold=50, service_type='DBInstanceIdentifier')
        apply_alarms(db_instance, cw, "FreeStorageSpace", comparison="<=", threshold=500, service_type='DBInstanceIdentifier')
        apply_alarms(db_instance, cw, "DatabaseConnections", threshold=100, service_type='DBInstanceIdentifier')
        # Investigate: FreeableMemory



