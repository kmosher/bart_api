import re
from urllib import urlencode
from urllib2 import urlopen
from xml.etree import ElementTree

class BartApiException(Exception): pass

def get_xml(url, debug=False):
    raw_response = urlopen(url)
    xml = parse_response(raw_response)
    if debug: ElementTree.dump(xml)
    errors = xml.find('message/error')
    if errors is not None:
        raise BartApiException(errors.findtext('text'), errors.findtext('details'))
    return xml

def parse_response(raw_xml):
    if isinstance(raw_xml, bytes):
      parsed_xml = ElementTree.fromstring(raw_xml, parser=ElementTree.XMLParser(encoding='utf-8'))
    else:
      parsed_xml = ElementTree.parse(raw_xml)
    return parsed_xml

def etree_to_dict(element_tree):
    if element_tree is None:
        return {}
    return {elt.tag: elt.text for elt in element_tree}

def element_to_dict(element):
    return {camel_to_snake(k): v for k, v in element.items()}

# From http://stackoverflow.com/a/1176023
def camel_to_snake(string):
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', string)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


class Station(object):

    def __init__(self, abbreviation, name=None):
        self.abbreviation = abbreviation.upper()
        self.name = name

    def __hash__(self):
        return hash(self.abbreviation)

    def __str__(self):
        if self.name is not None:
            return self.name
        else:
            return self.abbreviation

    def __repr__(self):
        return self.abbreviation

class BartApi(object):
    def __init__(self, api_root='http://api.bart.gov/api', api_key='MW9S-E7SL-26DU-VV8V'):
        self.api_root = api_root
        self.api_key = api_key
        self.debug = False

    def call(self, servlet, cmd, **kwargs):
        kwargs = {k: v for k, v in kwargs.iteritems() if v is not None}
        kwargs.update({'cmd': cmd, 'key': self.api_key})
        url = '{}/{}.aspx?{}'.format(
            self.api_root,
            servlet,
            urlencode(kwargs))
        return get_xml(url, self.debug)

    def number_of_trains(self):
        return int(self.call('bsa', 'count').findtext('traincount'))

    def elevator_status(self):
        return self.call('bsa', 'elev').findtext('bsa/description')

    def get_advisories(self, station='ALL'):
        bsas = self.call('bsa', 'bsa', orig=station).findall('bsa')
        return [{elm.findtext('station'): elm.findtext('description')} for elm in bsas]

    def get_stations(self):
        stations = self.call('stn', 'stns').findall('stations/station')
        return [etree_to_dict(station) for station in stations]

    def station_info(self, station):
        station_elm = self.call('stn', 'stninfo', orig=station).find('stations/station')
        if station_elm is None:
            raise BartApiException('No station info found for "%s"' % station)
        return etree_to_dict(station_elm)

    def station_access(self, station, legend="0"):
        station_elm = self.call('stn', 'stnaccess', orig=station, l=legend).find('stations/station')
        if station_elm is None:
            raise BartApiException('No station access info found for "%s"' % station)
        station_dict = etree_to_dict(station_elm)
        station_dict['flags'] = element_to_dict(station_elm)
        return station_dict

    def _etds_to_dict(self, etds):
        departures = {}
        for etd in etds:
            station = Station(etd.findtext('abbreviation'), etd.findtext('destination'))
            departures[station] = [etree_to_dict(elt) for elt in etd.findall('estimate')]
        return departures

    def departure_info(self, station, platform=None, direction=None):
        xml = self.call('etd', 'etd', orig=station, platform=platform, direction=direction)
        return self._etds_to_dict(xml.findall('station/etd'))

    def all_departure_info(self):
        xml = self.call('etd', 'etd', orig='ALL')
        return {Station(station.findtext('abbr'), station.findtext('name')):
                self._etds_to_dict(station.findall('etd'))
                for station in xml.findall('station')}

    def routes(self, date=None, schedule=None):
        xml = self.call('route', 'routes', date=date, sched=schedule)
        return [etree_to_dict(route) for route in xml.findall("routes/route")]

    def _route_to_dict(self, route_elm):
        route = etree_to_dict(route_elm)
        del route['config']
        route['stations'] = list(route_elm.find("config").itertext())
        return route

    def route_info(self, route, date=None, schedule=None):
        xml = self.call('route', 'routeinfo', route=route, date=date, sched=schedule)
        return self._route_to_dict(xml.find('routes/route'))

    def all_route_info(self, date=None, schedule=None):
        xml = self.call('route', 'routeinfo', route='all', date=date, sched=schedule)
        return [self._route_to_dict(route) for route in xml.findall('routes/route')]

    def fare(self, origin, dest, date=None, schedule=None):
        xml = self.call('sched', 'fare', orig=origin, dest=dest, date=date, sched=schedule)
        trip = etree_to_dict(xml.find('trip'))
        trip['discount'] = etree_to_dict(xml.find('trip/discount'))
        return trip

    def holidays(self):
        xml = self.call('sched', 'holiday')
        return [etree_to_dict(holiday) for holiday in xml.findall('holidays/holiday')]

    def route_schedule(self, route, date=None, schedule=None,):
        xml = self.call('sched', 'routesched', route=route, date=date, sched=schedule)
        return {int(train.get('index')): [element_to_dict(stop) for stop in train.findall('stop')]
                for train in xml.findall('route/train')}

    def schedules(self):
        xml = self.call('sched', 'scheds')
        return [element_to_dict(schedule) for schedule in xml.findall('schedules/schedule')]

    def special_schedules(self):
        xml = self.call('sched', 'special')
        return [etree_to_dict(schedule) for schedule in
                xml.findall('special_schedules/special_schedule')]

    def station_schedule(self, station, date=None):
        xml = self.call('sched', 'stnsched', orig=station, date=date)
        return [element_to_dict(item) for item in xml.findall('station/item')]

    def get_item(self, item_name, xml):
        item_list = xml.findall(".//" + item_name)
        if len(item_list) == 1:
            return [item_list[0].text]
        else:
            list_of_items = []
            for entry in item_list:
                    list_of_items.append(entry.text)
            return list_of_items


