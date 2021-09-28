#! /usr/bin/env python
import argparse

import boto
import boto.ec2
import boto.ec2.cloudwatch
import boto.ec2.elb
import boto.elasticache
import boto.rds
import sys
import time
import logging
import datetime

# Handle arguments
parser = argparse.ArgumentParser(description='Automatically create alerts')
parser.add_argument('-p', '--profile-name', default='default')
parser.add_argument('-r', '--aws-region', default='us-west-2')
parser.add_argument('-s', '--sns-topic')
parser.add_argument('-v', '--verbose', help="Set logging level to INFO", action="store_true")
parser.add_argument('-vv', '--verbose-debug', help="Set logging level to DEBUG", action="store_true")
args = parser.parse_args()

profile_name = args.profile_name
region       = args.aws_region
sns_topic    = args.sns_topic

if args.verbose:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
elif args.verbose_debug:
    logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)
else:
    logging.basicConfig(stream=sys.stderr, level=logging.WARN)

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
            logging.error("Unit not recognized: %s" % unit)
            return None
    else:
        # It's already in the format we want if it's all numbers; just convert to int
        return int(metric)

def instance_stats(instance_type):
    ec2_instance_types = {
        "t2.nano"     : { "vCPU":  1, "cph":    3, "Memory" :  0.5 },
        "t2.micro"    : { "vCPU":  1, "cph":    6, "Memory" :    1 },
        "t2.small"    : { "vCPU":  1, "cph":   12, "Memory" :    4 },
        "t2.medium"   : { "vCPU":  2, "cph":   24, "Memory" :    4 },
        "t2.large"    : { "vCPU":  2, "cph":   36, "Memory" :    8 },
        "t2.xlarge"   : { "vCPU":  4, "cph":   54, "Memory" :   16 },
        "t2.2xlarge"  : { "vCPU":  8, "cph":   81, "Memory" :   32 },
        "t3.nano"     : { "vCPU":  1, "cph":    3, "Memory" :  0.5 },
        "t3.micro"    : { "vCPU":  1, "cph":    6, "Memory" :    1 },
        "t3.small"    : { "vCPU":  1, "cph":   12, "Memory" :    4 },
        "t3.medium"   : { "vCPU":  2, "cph":   24, "Memory" :    4 },
        "t3.large"    : { "vCPU":  2, "cph":   36, "Memory" :    8 },
        "t3.xlarge"   : { "vCPU":  4, "cph":   54, "Memory" :   16 },
        "t3.2xlarge"  : { "vCPU":  8, "cph":   81, "Memory" :   32 },
        "m3.medium"   : { "vCPU":  2, "cph": None, "Memory" : 3.75 },
        "m3.large"    : { "vCPU":  2, "cph": None, "Memory" :  7.5 },
        "m3.xlarge"   : { "vCPU":  2, "cph": None, "Memory" :   15 },
        "m3.2xlarge"  : { "vCPU":  2, "cph": None, "Memory" :   30 },
        "m4.large"    : { "vCPU":  2, "cph": None, "Memory" :    8 },
        "m4.xlarge"   : { "vCPU":  2, "cph": None, "Memory" :   16 },
        "m4.2xlarge"  : { "vCPU":  2, "cph": None, "Memory" :   32 },
        "m4.4xlarge"  : { "vCPU":  2, "cph": None, "Memory" :   64 },
        "m4.10xlarge" : { "vCPU":  2, "cph": None, "Memory" :  160 },
        "m4.16xlarge" : { "vCPU":  2, "cph": None, "Memory" :  256 },
        "m5.large"    : { "vCPU":  2, "cph": None, "Memory" :    8 },
        "m5.xlarge"   : { "vCPU":  2, "cph": None, "Memory" :   16 },
        "m5.2xlarge"  : { "vCPU":  2, "cph": None, "Memory" :   32 },
        "m5.4xlarge"  : { "vCPU":  2, "cph": None, "Memory" :   64 },
        "m5.10xlarge" : { "vCPU":  2, "cph": None, "Memory" :  160 },
        "m5.16xlarge" : { "vCPU":  2, "cph": None, "Memory" :  256 },
        "c3.large"    : { "vCPU":  2, "cph": None, "Memory" : 3.75 },
        "c3.xlarge"   : { "vCPU":  4, "cph": None, "Memory" :  7.5 },
        "c3.2xlarge"  : { "vCPU":  8, "cph": None, "Memory" :   15 },
        "c3.4xlarge"  : { "vCPU": 16, "cph": None, "Memory" :   30 },
        "c3.8xlarge"  : { "vCPU": 32, "cph": None, "Memory" :   60 },
        "c4.large"    : { "vCPU":  2, "cph": None, "Memory" : 3.75 },
        "c4.xlarge"   : { "vCPU":  4, "cph": None, "Memory" :  7.5 },
        "c4.2xlarge"  : { "vCPU":  8, "cph": None, "Memory" :   15 },
        "c4.4xlarge"  : { "vCPU": 16, "cph": None, "Memory" :   30 },
        "c4.8xlarge"  : { "vCPU": 36, "cph": None, "Memory" :   60 },
        "c5.large"    : { "vCPU":  2, "cph": None, "Memory" : 3.75 },
        "c5.xlarge"   : { "vCPU":  4, "cph": None, "Memory" :  7.5 },
        "c5.2xlarge"  : { "vCPU":  8, "cph": None, "Memory" :   15 },
        "c5.4xlarge"  : { "vCPU": 16, "cph": None, "Memory" :   30 },
        "c5.9xlarge"  : { "vCPU": 36, "cph": None, "Memory" :   72 },
        "r3.large"    : { "vCPU":  2, "cph": None, "Memory" :15.25 },
        "r3.xlarge"   : { "vCPU":  4, "cph": None, "Memory" : 30.5 },
        "r3.2xlarge"  : { "vCPU":  8, "cph": None, "Memory" :   61 },
        "r3.4xlarge"  : { "vCPU": 16, "cph": None, "Memory" :  122 },
        "r3.8xlarge"  : { "vCPU": 32, "cph": None, "Memory" :  244 },
        "r4.large"    : { "vCPU":  2, "cph": None, "Memory" :15.25 },
        "r4.xlarge"   : { "vCPU":  4, "cph": None, "Memory" : 30.5 },
        "r4.2xlarge"  : { "vCPU":  8, "cph": None, "Memory" :   61 },
        "r4.4xlarge"  : { "vCPU": 16, "cph": None, "Memory" :  122 },
        "r4.8xlarge"  : { "vCPU": 32, "cph": None, "Memory" :  244 },
        "r4.16xlarge" : { "vCPU": 64, "cph": None, "Memory" :  488 },
        "r5.large"    : { "vCPU":  2, "cph": None, "Memory" :15.25 },
        "r5.xlarge"   : { "vCPU":  4, "cph": None, "Memory" : 30.5 },
        "r5.2xlarge"  : { "vCPU":  8, "cph": None, "Memory" :   61 },
        "r5.4xlarge"  : { "vCPU": 16, "cph": None, "Memory" :  122 },
        "r5.8xlarge"  : { "vCPU": 32, "cph": None, "Memory" :  244 },
        "r5.16xlarge" : { "vCPU": 64, "cph": None, "Memory" :  488 },
        "x1.16xlarge" : { "vCPU": 64, "cph": None, "Memory" :  976 },
        "x1.32xlarge" : { "vCPU":128, "cph": None, "Memory" : 1952 }
    }
    class instance_obj():
        pass

    instance_type = instance_type.replace("db.", '')
    i = instance_obj()
    i.cpu = ec2_instance_types[instance_type]["vCPU"]
    i.cph = ec2_instance_types[instance_type]["cph"]
    # I found that my r3.large instances don't have CPUCreditBalances, so I needed
    # to not give them a default amount.  Added check so only RDS inst. w/cph will 
    # get the alarm.
    if i.cph is None and not any(word in instance_type for word in ['r3.large']):
        i.cph = 50
    i.ram = ec2_instance_types[instance_type]["Memory"]
    return i

# Get list of instances
def get_ec2_instances(profile_name):
    ec2 = boto.ec2.connect_to_region(region,profile_name=profile_name)
    reservations = ec2.get_all_reservations()
    inst = []
    for reservation in reservations:
        for instance in reservation.instances:
            try:
                instance.name = instance.tags['Name']
            except:
                instance.name = None
            instance.nametag = instance.id
            inst.append(instance)
    return inst

def get_elasticache_instances(profile_name):
    ec = boto.elasticache.connect_to_region(region,profile_name=profile_name)
    ec_clusters = []
    class ec_obj():
        pass
    for cluster in ec.describe_cache_clusters().values()[0]['DescribeCacheClustersResult']['CacheClusters']:
        c = ec_obj()
        c.nametag = str(cluster['CacheClusterId'])
        c.cluster = cluster
        ec_clusters.append(c)
    return ec_clusters

def get_rds_instances(profile_name):
    rds = boto.rds.connect_to_region(region,profile_name=profile_name)
    rds_instances = []
    for instance in rds.get_all_dbinstances():
        instance.nametag = str(instance.id)
        rds_instances.append(instance)
    return rds_instances

def get_elb_instances(profile_name):
    elb = boto.ec2.elb.connect_to_region(region,profile_name=profile_name)
    elb_instances = []
    for instance in elb.get_all_load_balancers():
        instance.nametag = instance.name
        elb_instances.append(instance)
    return elb_instances

def get_alarms(cloudwatch_connection):
    alarm_obj = cloudwatch_connection.describe_alarms()
    active_alarms = [ x.name for x in alarm_obj ]
    # describe_alarms paginates so we have to take effort to get them all
    while alarm_obj.next_token:
        alarm_obj = cloudwatch_connection.describe_alarms(next_token=alarm_obj.next_token)
        active_alarms += [x.name for x in alarm_obj]
    return active_alarms

def apply_alarms(instance_id, cloudwatch_connection, instance_metrics,
                 prefix='', comparison=">=", threshold=1, period=60, name="",
                 evaluation_periods=5, statistic='Average', sns_topic=sns_topic, 
                 dimension_name = 'InstanceId', active_alarms = [], force=False):

    if isinstance(instance_metrics, str):
        instance_metrics = [instance_metrics]
    if isinstance(instance_id, str) or isinstance(instance_id, unicode):
        instance_id = [instance_id]
    if prefix:
        prefix = '%s-' % prefix

    if len(active_alarms) == 0:
        active_alarms = get_alarms(cw)

    threshold = metric_human_readable(threshold)

    for instance_metric in instance_metrics:
        if not name:
            name = instance_metric
        if len(instance_id) > 1:
            instance_name = instance_id[1]
            metric_name = "%s-%s%s-%s" % (profile_name,prefix,instance_name,name)
            instance_id = instance_id[0]
        else:
            instance_id = instance_id[0]
            metric_name = "%s-%s%s-%s" % (profile_name,prefix,instance_id,name)

        if metric_name in active_alarms and not force:
            logging.info("Metric %s is already configured" % metric_name)
        elif "test" in metric_name.lower():
            logging.info("Not creating %s; is a test box." % metric_name)
        elif "Packer" in metric_name:
            logging.info("Not creating %s; is a transient Packer box." % metric_name)
        elif all(x in metric_name.lower() for x in ["ec2", "i-"]):
            logging.info("EC2 instance %s is unnamed.  Not important enough to check." % metric_name)
        else:
            metric = cloudwatch_connection.list_metrics(dimensions={dimension_name:instance_id}, metric_name=instance_metric)
            if len(metric) > 0:
                logging.info("Active alarms %s" % len(active_alarms))
                logging.warn("Creating metric for %s (%s): %s" % (instance_id,metric_name,metric[0]))
                metric[0].create_alarm(name=metric_name,
                                       comparison=comparison,
                                       threshold=threshold,
                                       period=period,
                                       evaluation_periods=evaluation_periods,
                                       statistic=statistic,
                                       alarm_actions=[sns_topic],
                                       ok_actions=[sns_topic])
                time.sleep(0.5)

def get_ebs_volumes(profile_name):
    ec2 = boto.ec2.connect_to_region(region,profile_name=profile_name)
    ebs_volumes = []
    volumes = ec2.get_all_volumes()
    for v in volumes:
        ebs_volumes.append(v.id)
    return ebs_volumes

def weekly_cleanup_insufficients(cloudwatch_connection):
    # When a server gets deleted, the alarms will show up as INSUFFICIENT_DATA
    # from then on.  This can happen normally as well, but it's usually
    # transient.  This function deletes all alarms in that state, trusting
    # that subsequent runs will add them back in.
    day = datetime.datetime.today().weekday()
    hour = datetime.datetime.today().hour
    if day == 0 and hour == 8:
        alarm_obj = cloudwatch_connection.describe_alarms()
        #insufficient_alarms = []
        while alarm_obj.next_token:
            alarm_obj = cloudwatch_connection.describe_alarms(next_token=alarm_obj.next_token)
            for a in alarm_obj:
                if a.state_value == "INSUFFICIENT_DATA":
                    logging.warn("Deleting alarm %s which is no longer reporting back." % a.name)
                    a.delete()
                    # Forgot there's a rate limit issue
                    time.sleep(0.5)

if __name__ == '__main__':
    cw  = boto.ec2.cloudwatch.connect_to_region(region,profile_name=profile_name)

    # This only runs during the 8AM hour on Monday
    weekly_cleanup_insufficients(cw)

    active_alarms = get_alarms(cw)
    logging.warn("Got %s alarms already configured." % len(active_alarms))

    # EC2 Instances
    # Note: DiskSpaceUtilization is a custom metric; you'd need to roll your own to get that.
    ec2_args = { "prefix": "ec2", "active_alarms": active_alarms }
    for instance_id in get_ec2_instances(profile_name):
        nCPU = instance_stats(instance_id.instance_type).cpu
        cpu_credit_rate = instance_stats(instance_id.instance_type).cph
        inst_name = instance_id.nametag
        if instance_id.name:
            inst_name = [ instance_id.id, instance_id.name ]
        apply_alarms(inst_name, cw, "CPUCreditBalance", comparison="<=", threshold=10 * cpu_credit_rate, **ec2_args)
        apply_alarms(inst_name, cw, "StatusCheckFailed", **ec2_args)
        apply_alarms(inst_name, cw, "MemoryUtilization", threshold=80, **ec2_args)
        apply_alarms(inst_name, cw, "CPUUtilization", threshold=90 * nCPU, **ec2_args)
        apply_alarms(inst_name, cw, "DiskSpaceUtilization", threshold=50, **ec2_args)
    
    # Elasticache
    # EC2 local disk - EBS Volumes
    ebs_args = { "prefix": "ebs", "active_alarms": active_alarms, "dimension_name": "VolumeId" }
    for vol in get_ebs_volumes(profile_name):
        apply_alarms(vol, cw, "BurstBalance", comparison="<=", threshold=60, period=300, **ebs_args)

    ec_args = { "prefix" : "elasticache", "active_alarms" : active_alarms, "dimension_name": "CacheClusterId" }
    for cluster_instance in get_elasticache_instances(profile_name):
        # I was getting alarms in swap usage when we weren't pegged for memory.  BytesUsedForCache is a better check
        #apply_alarms(cluster_instance.nametag, cw, "SwapUsage", threshold='100mb', comparison=">=", **ec_args)
        apply_alarms(cluster_instance.nametag, cw, "BytesUsedForCache", threshold='300mb', comparison=">=", **ec_args)
        apply_alarms(cluster_instance.nametag, cw, "Evictions", threshold='20', comparison=">=", **ec_args)
        apply_alarms(cluster_instance.nametag, cw, "CurrConnections", threshold='250', comparison=">=", **ec_args)
        apply_alarms(cluster_instance.nametag, cw, "FreeableMemory", threshold='1gb', comparison="<=", **ec_args)
    
    # RDS
    rds_args = { "prefix": "rds", "dimension_name": "DBInstanceIdentifier", "active_alarms": active_alarms }
    for db_instance in get_rds_instances(profile_name):
        apply_alarms(db_instance.nametag, cw, "SwapUsage", threshold='1gb', **rds_args)
        apply_alarms(db_instance.nametag, cw, "CPUUtilization", threshold=80, force=True, **rds_args)
        if instance_stats(db_instance.instance_class).cph:
            apply_alarms(db_instance.nametag, cw, "CPUCreditBalance", comparison="<=", threshold=50, **rds_args)
        if db_instance.allocated_storage > 0:
            twenty_percent = int(db_instance.allocated_storage * 0.2)
            ten_percent = int(db_instance.allocated_storage * 0.1)
            apply_alarms(db_instance.nametag, cw, "FreeStorageSpace", comparison="<=", threshold='%dgb' % ten_percent, **rds_args)
        else:
            # I don't have an easy way to calculate this; it's based on instance size, and a t2.small regularly has 25GB free
            apply_alarms(db_instance.nametag, cw, "FreeLocalStorage", comparison="<=", threshold='15gb', **rds_args)
        apply_alarms(db_instance.nametag, cw, "EngineUptime", comparison="<=", threshold='50000', **rds_args)

        available_memory_gb = instance_stats(db_instance.instance_class).ram
        # 90% of the aws calculation for default connection maximum
        threshold = ((available_memory_gb * 1024 * 1024 * 1024) / 12582880) * 0.9
        apply_alarms(db_instance.nametag, cw, "DatabaseConnections", threshold=threshold, **rds_args)
        # Investigate: FreeableMemory

    # ELB
    elb_args = { "prefix": "elb", "dimension_name": "LoadBalancerName", "active_alarms": active_alarms, "evaluation_periods": 2 }
    for elb_instance in get_elb_instances(profile_name):
        if "AppELBTes" not in elb_instance.nametag and "gonefishing" not in elb_instance.nametag:
            apply_alarms(elb_instance.nametag, cw, "UnHealthyHostCount", statistic='Minimum', comparison=">=", **elb_args)
            apply_alarms(elb_instance.nametag, cw, "HealthyHostCount", statistic='Maximum', comparison="<", threshold=2, **elb_args)
            apply_alarms(elb_instance.nametag, cw, "HTTPCode_Backend_5XX", statistic='SampleCount', comparison=">", threshold=100, **elb_args)

    logging.warn("No other alarms to create.")


