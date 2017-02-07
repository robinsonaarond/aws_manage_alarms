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

def metric_human_readable(metric):
    # Support k/K/kb/KB = Kilobyte, m/M/mb/MB = Megabyte, g/G/gb/GB = Gigabyte, t/T/tb/TB = Terabyte
    #   e.g., converts '5GB' of str to 5368709120 of int

    if not isinstance(metric, basestring):
        # Any non-strings we'd just try to int-ify.
        return int(metric)

    unit = ''.join([i for i in metric if not i.isdigit()]).lower()
    if unit:
        digits = float(''.join([i for i in metric if i.isdigit()]))
        if unit in [ 'k', 'kb' ]:
            return int(digits * 1024)
        elif unit in [ 'm', 'mb' ]:
            return int(digits * 1048576)
        elif unit in [ 'g', 'gb' ]:
            return int(digits * 1073741824)
        elif unit in [ 't', 'tb' ]:
            return int(digits * 1099511627776)
        else:
            print "Unit not recognized: %s" % unit
            return None
    else:
        # It's already in the format we want if it's all numbers; just convert to int
        return int(metric)

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

def get_alarms(cloudwatch_connection):
    alarm_obj = cloudwatch_connection.describe_alarms()
    active_alarms = [ x.name for x in alarm_obj ]
    # describe_alarms paginates so we have to take effort to get them all
    while alarm_obj.next_token:
        alarm_obj = cloudwatch_connection.describe_alarms(next_token=alarm_obj.next_token)
        active_alarms += [x.name for x in alarm_obj]
    return active_alarms

def apply_alarms(instance_id, cloudwatch_connection, instance_metrics,
                 prefix='', comparison=">=", threshold=1, period=60, 
                 evaluation_periods=5, statistic='Average', sns_topic=sns_topic, 
                 service_type = 'InstanceId', active_alarms = [], force=False):

    if isinstance(instance_metrics, str):
        instance_metrics = [instance_metrics]
    if isinstance(instance_id, str):
        instance_id = [instance_id]
    if prefix:
        prefix = '%s-' % prefix

    if len(active_alarms) == 0:
        active_alarms = get_alarms()

    threshold = metric_human_readable(threshold)

    for instance_metric in instance_metrics:
        if len(instance_id) > 1:
            instance_name = instance_id[1]
            metric_name = "%s-%s%s-%s" % (profile_name,prefix,instance_name,instance_metric)
            instance_id = instance_id[0]
        else:
            instance_id = instance_id[0]
            metric_name = "%s-%s%s-%s" % (profile_name,prefix,instance_id,instance_metric)

        if metric_name in active_alarms and not force:
            print "Metric %s is already configured" % metric_name
        elif "test" in metric_name.lower():
            print "Not creating %s; is a test box." % metric_name
        elif all(x in metric_name.lower() for x in ["ec2", "i-"]):
            #print "EC2 instance %s is unnamed.  Not important enough to check." % metric_name
            pass
        else:
            metric = cloudwatch_connection.list_metrics(dimensions={service_type:instance_id}, metric_name=instance_metric)
            if len(metric) > 0:
                print "Active alarms", len(active_alarms)
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

    active_alarms = get_alarms(cw)
    print "Got %s alarms already configured." % len(active_alarms)

    # EC2 Instances
    # Note: DiskSpaceUtilization is a custom metric; you'd need to roll your own to get that.
    for instance_id in get_ec2_instances(profile_name):
        apply_alarms(instance_id, cw, "CPUCreditBalance", prefix="ec2", active_alarms=active_alarms, comparison="<=", threshold=50)
        apply_alarms(instance_id, cw, "StatusCheckFailed", prefix="ec2", active_alarms=active_alarms)
        apply_alarms(instance_id, cw, "MemoryUtilization", prefix="ec2", active_alarms=active_alarms, threshold=80)
        apply_alarms(instance_id, cw, "DiskSpaceUtilization", prefix="ec2", active_alarms=active_alarms, threshold=80)
    
    # Elasticache
    for cluster_instance in get_elasticache_instances(profile_name):
        apply_alarms(cluster_instance, cw, "SwapUsage", prefix='elasticache', active_alarms=active_alarms, threshold='1gb', service_type='CacheClusterId')
    
    # RDS
    for db_instance in get_rds_instances(profile_name):
        apply_alarms(db_instance, cw, "SwapUsage", prefix="rds", active_alarms=active_alarms, threshold='1gb', service_type='DBInstanceIdentifier')
        apply_alarms(db_instance, cw, "CPUCreditBalance", prefix="rds", active_alarms=active_alarms, comparison="<=", threshold=50, service_type='DBInstanceIdentifier')
        apply_alarms(db_instance, cw, "FreeStorageSpace", prefix="rds", active_alarms=active_alarms, comparison="<=", threshold=500, service_type='DBInstanceIdentifier')
        apply_alarms(db_instance, cw, "DatabaseConnections", prefix="rds", active_alarms=active_alarms, threshold=100, service_type='DBInstanceIdentifier')
        # Investigate: FreeableMemory



