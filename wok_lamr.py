import threading
import time

import requests

import xml.etree.cElementTree as et

import ConfigParser


def chunks(l, n):
    """Yield successive n-sized chunks from l."""
    for i in xrange(0, len(l), n):
        yield l[i:i+n]


class WebOfScienceAPI:
    """Manage requests to the WoS LAMR API, and parse the returned data.

    Details: http://wokinfo.com/products_tools/products/related/trlinks/
    """

    # The WOS API limits the number of papers per request.
    request_limit = 50

    # This might need to be tuned, I found 10-50 threads to be optimum.
    max_threads = 10

    url = "https://ws.isiknowledge.com/cps/xrpc"
    post_request = lambda self, data: requests.post(self.url, data)

    def __init__(self, papers):
        self.papers = papers
        self.npapers = len(self.papers)

    def create_request_data(self, idname, vector):
        """Create XML data consumable by the WOS API, specifying a paper by specific ID."""

        src = 'app.id=MyApp,env.id=MyEnv,partner.email=myemail'

        xml_request = et.Element('request', {'xmlns' : 'http://www.isinet.com/xrpc42', 'src' : src})
        xml_fn = et.SubElement(xml_request, 'fn', {'name' : 'LinksAMR.retrieve'})
        xml_list = et.SubElement(xml_fn, "list")
        xml_who = et.SubElement(xml_list, "map")

        # We want the UT, DOI and PMID to come back with the citation count.
        xml_what = et.SubElement(xml_list, "map")
        xml_wos = et.SubElement(xml_what, 'list', {'name':'WOS'})
        xml_wos_ut = et.SubElement(xml_wos, "val")
        xml_wos_ut.text = "ut"
        xml_wos_doi = et.SubElement(xml_wos, "val")
        xml_wos_doi.text = "doi"
        xml_wos_pmid = et.SubElement(xml_wos, "val")
        xml_wos_pmid.text = "pmid"
        xml_wos_tc = et.SubElement(xml_wos, "val")
        xml_wos_tc.text = "timesCited"
        xml_wos_timescited = et.SubElement(xml_wos, "val")
        xml_wos_timescited.text = "timesCited"

        # We are requesting data for a bunch of articles in one go here, each by the same id (UT/PMID/DOI).
        # The name of each paper is just the index in the vector passed to this method,
        # which needs to be used when parsing the response, since the order is not conserved.
        xml_papers = et.SubElement(xml_list, "map")
        for i,value in enumerate(vector):
            xml_paper = et.SubElement(xml_papers, "map", { 'name' : str(i) })
            xml_val = et.SubElement(xml_paper, "val", { 'name' : idname })
            xml_val.text = value

        return et.tostring(xml_request, encoding="UTF-8", method="xml")

    def requests2responses(self, request_data, max_threads=None):
        """Throw data at the WOS API in several threads."""

        max_threads = max_threads or self.max_threads

        # Each thread will execute this function once, filling up a list of None values,
        # putting in empty dicts and then response dicts, until there are no more None value.
        # This simple design allows threads to detect which requests have been sent and
        # are pending and which have not been sent yet, since the empty dict is assigned
        # BEFORE a request is sent. In case of ConnectionError (seems to happen sometimes
        # with many requests) we want to try the request again, so reset corresonding
        # value to None and continue.
        responses = [None]*len(request_data)
        def fetch():
            while None in responses:
                i = responses.index(None)
                responses[i] = {}
                try:
                    responses[i] = self.post_request(request_data[i])
                except requests.ConnectionError:
                    print "ConnectionError: will retry %i=0 later." %i
                    responses[i] = None

        for i in range(min(max_threads, len(request_data))):
            threading.Thread(target=fetch).start()

        while (None in responses) or ({} in responses):
            time.sleep(0.50)

        return responses

    def response2papers(self, res):
        """Parse WOS API output (XML) into a list of dicts."""

        response = et.fromstring(res.content).getchildren()[0]
        fn = response.getchildren()[0]
        outermap = response.getchildren()[0]

        # The papers in the XML response come back in a different order, so we need
        # to correct that. That is why we first gather all papers into a dict where
        # the name (index as string -- see create_request_data above) is the key,
        # and then transform that dict into a list ordered by those indices.
        papers_dict = {}
        for paper_map in outermap.getchildren():
            paper_name = paper_map.attrib['name']
            papers_dict[paper_name] = {}
            map_wos = paper_map.getchildren()[0]
            for field in map_wos.getchildren():
                papers_dict[paper_name][field.attrib['name']] = field.text

        # This is just a sanity check to make sure all indices up to the cardinality
        # of the dict are present as string keys.
        for i in range(len(papers_dict)):
            assert papers_dict.has_key(str(i))

        return [papers_dict[str(i)] for i in range(len(papers_dict))]

    def fetch_by_id(self, type):
        """Control fetching from the API by a specific id (UT/PMID/DOI)."""

        # Group all the indices and IDs into chunks that are consistent with request size
        # limits imposed by the WOS API, and generate the XML data to be sent.
        indices = chunks(range(self.npapers), self.request_limit)
        ids = [[self.papers[i][type] for i in ind] for ind in indices]
        datas = [self.create_request_data(type, v) for v in ids]

        # This is the most time consuming part, still below half a minute for over 2000 articles
        # when 5 threads are used. Increasing the thread count up to 50 seems to work,
        # but sometimes produces ConnectionError. So, still make sure to check for that
        # when sending requests in requests2repsonses for each thread separately.
        print "Fetching %i papers by %s in %i requests..." %(self.npapers, type.upper(), len(datas))
        responses = self.requests2responses(datas)

        # The double list comprehension below flattens the papers returned by response2papers
        # into a single list. Note that keeping the 'No Results Found' condition inside the loop
        # ensures that the order of articles will be conserved, and those not found will be
        # returned as None. We want to do some checking on the returned list, here just assert
        # that the ID used to search each paper is returned with the same value.
        returned = [p for r in responses for p in self.response2papers(r)]
        found = [None] * self.npapers
        for i,p in enumerate(returned):
            if p.get('message','') != 'No Result Found':
                found[i] = p
                assert p[type].lower() == self.papers[i][type].lower()

        return found

    def fetch_by_pmid(self):
        return self.fetch_by_id('pmid')

    def fetch_by_doi(self):
        return self.fetch_by_id('doi')
