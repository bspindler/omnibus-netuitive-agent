"""
handler to flush stats to [NetuitiveCloud](http://www.netuitive.com)
#### Dependencies

#### Configuration
Enable handler

  * handlers = diamond.handler.netuitive.NetuitiveHandler

  * url = https://api.app.netuitive.com
  * api_key = NETUITIVE_API_KEY
  * tags = tag1:tag1val, tag2:tag2val

"""

from Handler import Handler
import logging
import re
import platform
import datetime
import os
import json
import urllib2
from diamond.util import get_diamond_version

try:
    import psutil
except ImportError:
    psutil = None

try:
    import netuitive
except ImportError:
    netuitive = None


def get_human_readable_size(num):
    exp_str = [(0, 'B'), (10, 'KB'), (20, 'MB'),
               (30, 'GB'), (40, 'TB'), (50, 'PB'), ]
    i = 0
    while i + 1 < len(exp_str) and num >= (2 ** exp_str[i + 1][0]):
        i += 1
        rounded_val = round(float(num) / 2 ** exp_str[i][0], 2)
    return '%s %s' % (int(rounded_val), exp_str[i][1])


def check_lsb():
    try:
        _distributor_id_file_re = re.compile("(?:DISTRIB_ID\s*=)\s*(.*)", re.I)
        _release_file_re = re.compile("(?:DISTRIB_RELEASE\s*=)\s*(.*)", re.I)
        _codename_file_re = re.compile("(?:DISTRIB_CODENAME\s*=)\s*(.*)", re.I)
        with open("/etc/lsb-release", "rU") as etclsbrel:
            for line in etclsbrel:
                m = _distributor_id_file_re.search(line)
                if m:
                    _u_distname = m.group(1).strip()
                m = _release_file_re.search(line)
                if m:
                    _u_version = m.group(1).strip()
                m = _codename_file_re.search(line)
                if m:
                    _u_id = m.group(1).strip()
            if _u_distname and _u_version:
                return (_u_distname, _u_version, _u_id)
    except Exception as e:
        logging.debug(e)
        return(None)


class NetuitiveHandler(Handler):

    def __init__(self, config=None):
        """
        initialize Netuitive api and populate agent host metadata
        """

        if not netuitive:
            self.log.error('netuitive import failed. Handler disabled')
            self.enabled = False
            return

        try:
            Handler.__init__(self, config)

            logging.debug("initialize Netuitive handler")
            self.api = netuitive.Client(
                self.config['url'], self.config['api_key'])

            self.element = netuitive.Element()

            self.batch_size = int(self.config['batch'])

            self.max_backlog_multiplier = int(
                self.config['max_backlog_multiplier'])

            self.trim_backlog_multiplier = int(
                self.config['trim_backlog_multiplier'])

            self._add_sys_meta()
            self._add_aws_meta()
            self._add_config_tags()

            logging.debug(self.config)

        except Exception as e:
            logging.exception('NetuitiveHandler: init - %s', str(e))

    def get_default_config_help(self):
        """
        Returns the help text for the configuration options for this handler
        """
        config = super(NetuitiveHandler, self).get_default_config_help()

        config.update({
            'url': 'NetuitiveCloud url to send data to',
            'api_key': 'Datasource api key',
            'tag': 'Netuitive Tags',
            'batch': 'How many to store before sending to the graphite server',
            'max_backlog_multiplier': 'how many batches to store before trimming',
            'trim_backlog_multiplier': 'Trim down how many batches',
        })
        return config

    def get_default_config(self):
        """
        Return the default config for the handler
        """

        config = super(NetuitiveHandler, self).get_default_config()

        config.update({
            'url': 'https://api.app.netuitive.com',
            'api_key': 'apikey',
            'tags': None,
            'batch': 100,
            'max_backlog_multiplier': 5,
            'trim_backlog_multiplier': 4,
        })
        return config

    def __del__(self):
        pass

    def _add_sys_meta(self):
        try:

            self.element.add_attribute('platform', platform.system())

            if psutil:
                self.element.add_attribute('cpus', psutil.cpu_count())
                mem = psutil.virtual_memory()
                self.element.add_attribute(
                    'ram', get_human_readable_size(mem.total))
                self.element.add_attribute('ram bytes', mem.total)
                self.element.add_attribute(
                    'boottime', str(datetime.datetime.fromtimestamp(psutil.boot_time())))

            if platform.system().startswith('Linux'):
                if check_lsb() is None:
                    supported_dists = platform._supported_dists + ('system',)
                    dist = platform.linux_distribution(
                        supported_dists=supported_dists)

                else:
                    dist = check_lsb()

                dist = platform.linux_distribution(
                    platform.linux_distribution(supported_dists=supported_dists))

                self.element.add_attribute('distribution_name', str(dist[0]))
                self.element.add_attribute(
                    'distribution_version', str(dist[1]))
                self.element.add_attribute('distribution_id', str(dist[2]))

            if os.path.isfile('/opt/netuitive-agent/version-manifest.txt'):
                with open('/opt/netuitive-agent/version-manifest.txt', 'r') as f:
                    v = f.readline()

                f.close()

                self.element.add_attribute(
                    'agent', v.replace(' ', '_').lower())

            else:
                self.element.add_attribute(
                    'agent', 'Diamond_' + get_diamond_version())

        except Exception as e:
            logging.info(e)
            pass

    def _add_aws_meta(self):
        url = 'http://169.254.169.254/latest/dynamic/instance-identity/document'

        try:
            request = urllib2.Request(url)
            resp = urllib2.urlopen(request, timeout=1).read()
            j = json.loads(resp)

            for k, v in j.items():
                if type(v) is list:
                    vl = ', '.join(v)
                    v = vl
                self.element.add_attribute(k, v)

        except Exception as e:
            logging.debug(e)
            pass

    def _add_config_tags(self):
        tags = self.config.get('tags')

        if tags is not None:
            if type(tags) is list:
                for k, v in dict(tag.split(":") for tag in tags).iteritems():
                    self.element.add_tag(k.strip(), v.strip())

            if type(tags) is str:
                self.element.add_tag(tags.split(":")[0], tags.split(":")[1])

    def process(self, metric):
        metricId = metric.getCollectorPath() + '.' + metric.getMetricPath()

        self.element.add_sample(
            metricId, metric.timestamp * 1000, metric.value, metric.metric_type, host=metric.host)

        if len(self.element.metrics) >= self.batch_size:
            self.flush()

    def flush(self):
        try:

            # Don't let too many metrics back up
            if len(self.element.metrics) >= (
                    self.batch_size * self.max_backlog_multiplier):
                trim_offset = (self.batch_size
                               * self.trim_backlog_multiplier * -1)
                logging.warn('NetuitiveHandler: Trimming backlog. Removing'
                             + ' oldest %d and keeping newest %d metrics',
                             len(self.element.metrics) - abs(trim_offset),
                             abs(trim_offset))
                self.element.metrics = self.element.metrics[trim_offset:]

            self.api.post(self.element)
            self.element.clear_samples()

        except Exception as e:
            logging.exception('NetuitiveHandler: flush - %s', str(e))