import cookielib
import errno
import random
import re
import socket
import sys
import time
import urllib
import urllib2

from BeautifulSoup import BeautifulSoup


class WebOfKnowledgeSearcher:
    """Automate the task of searching WoK for papers (gist.github.com/langner/7176205)."""

    wokurl = "http://www.webofknowledge.com"
    searchurl = "http://apps.webofknowledge.com/UA_GeneralSearch.do"
    summaryurl = "http://apps.webofknowledge.com/summary.do"

    uagent = 'Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 5.1; Mozilla/4.0 (compatible; MSIE 6.0; Windows NT 5.1; SV1) ; .NET CLR 2. '
    static_query_data = {
        'product' : 'UA',
        'parentProduct' : 'UA',
        'search_mode' : 'GeneralSearch',
        'period' : 'Range Selection',
        'range' : 'ALL'
    }

    def __init__(self, logfunc=None):

        # Only a certain number of queries are allowed per session, and there is typically
        # one POST request per query, followed by one or more additional GET request(s),
        # depending on the number of search results and pages they span. There are some
        # exceptions to incrementing the QueryID (qid), so take notice of code below
        # that synchronizes self.query_count with the parsed qid to be on the safe side.
        self.query_reset = 40
        self.session_count = 0
        self.query_count = 0
        self.post_request_count = 0
        self.get_request_count = 0

        # Note that this is a function that logs a message, not a logger object.
        logfunc = logfunc or (lambda msg: sys.stdout.writeline("%s\n" %msg))
        self._set_logfunc(logfunc)

        self._create_session()

    def _set_logfunc(self, logfunc):

        self.log = lambda msg: logfunc("Query %i - %s" % (self.query_count, msg))
        self.logger = self.log

    def _request(self, url, data=None):
        """Basic logic for making requests.

        Passing data to the request effectively makes it a POST request,
        otherwise it is a GET request (the URL may still contain encoded data).
        """

        if data:
            self.post_request_count += 1
            request = urllib2.Request(url, urllib.urlencode(data), headers={'User-agent' : self.uagent})
        else:
            self.get_request_count += 1
            request = urllib2.Request(url, headers={'User-agent' : self.uagent})

        if not request:
            self.log("Unable to connect to %s" % url)
            return -1

        try:
            return self.opener.open(request).read()
        except urllib2.URLError as e:
            self.log("Request error: %s" % e)
            return -1
        except socket.error as serr:
            if serr.errno != errno.ECONNREFUSED:
                raise serror
            self.log("Socket error: %s" % serr)
            return -1

    def _create_session(self):
        """Create a cookie and session, and get the session ID."""

        self.cookie_jar = cookielib.CookieJar() 
        self.opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(self.cookie_jar))
        urllib2.install_opener(self.opener)

        response = self._request(self.wokurl)
        try:
            self.SID = self.cookie_jar._cookies['.webofknowledge.com']['/']['SID'].value
        except KeyError as e:
            self.log("Unable to retrieve session ID from WoK (KeyError: %s)" % e)
            return -1

        self.session_count += 1

    def _prepare_session(self):
        """This should be called at least before each new query.

        Interpose some random delays, and make sure to reset the session
        after a certain amount of queryies.
        """

        if random.random() > 0.75:
            time.sleep(0.5*random.random())

        if (self.query_count > 0) and (self.query_count % self.query_reset == 0):
            self.log("Resetting connection with ISI Web of Knowledge.")
            self.opener.close()
            self.cookie_jar.clear_session_cookies()
            time.sleep(0.5 + 5.0*random.random())
            self._create_session()

    # This return a list of pagecounts in the response, and there should normally be just one.
    find_pagecounts = lambda self, resp: BeautifulSoup(resp).findAll("span", { "id" : "pageCount.top" })

    # This returns a list of soups, one for each search result item.
    find_results = lambda self, resp: BeautifulSoup(resp).findAll("div", { "class" : "search-results-item" })

    def _generic_query(self, data, pagesize=50):
        """Generic driver for performing queries.

        The general procedure is to POST a query to the server, and then subsequently use
        the current session and query IDs to increase the page size and iterate through
        all the pages in the result list.

        Should always return a 2-tuple, which on success contains a list of parsed data
        for each article in the result list and the total pagecount. When an error is encountered,
        typically return a negative integer as the first value of the tuple.
        """

        self.query_count += 1

        self._prepare_session()

        # This is the initial POST request.
        response = self._request(self.searchurl, data=data)
        if response == -1:
            return -1,0

        # If there pagecount length is not one, there were probably no results, and we need to bail out.
        # Also, getting the actual integer sometimes for pagecount sometimes fails when the formatting
        # of HTML is mangled so we want to return nothing in that case, too. It might be a better option,
        # however, to retry the request in such a case.
        pagecount = self.find_pagecounts(response)
        try:
            assert len(pagecount) == 1
            pagecount = int(pagecount[0].text)
        except AssertionError:
            self.log("Length of pagecount was not one, quitting query.")
            self.log("Request data: " + str(data))
            return [], 0
        except ValueError:
            self.log("Could not convert pagecount to integer, quitting query.")
            self.log("Request data: " + str(data))
            return [], 0

        # Sometimes the query ID is not incremented (for example for error repsonses). Instead of discovering
        # all the various conditions, parse the response for the current query ID and use that.
        qids = re.findall(r'&qid=\d+&', response)
        qids = list(set([int(q.strip("&").split('=')[1]) for q in qids]))
        if len(qids) != 1:
            self.log("Unable to parse a consistent query ID, something is wrong.")
            self.log("Request data: " + str(data))
            return -1, 0
        qid = qids[0]

        # Now change the page size if needed.
        if pagecount > 1:
            data = self.static_query_data.copy()
            data['qid'] = qid
            data['SID'] = self.SID
            data['action'] = 'changePageSize'
            data['pageSize'] = pagesize
            response = self._request(self.summaryurl + "?" + urllib.urlencode(data))
            if response == -1:
                return -1,0
            pagecount = self.find_pagecounts(response)
            try:
                assert len(pagecount) == 1
                pagecount = int(pagecount[0].text)
            except AssertionError:
                return [], 0

        # Gather all the parsed data from the first page.
        article_data = [self.parse_article_data(res) for res in self.find_results(response)]

        # This happens when the author names are popular or the title is very short.
        if pagecount > 10:
            self.log("Too many pages (%i) in response, using only first one." % pagecount)
            return article_data, 1

        # Finally, iterate over all pages if there are more. In case of any problems, we can
        # try to return the data we have collected hitherto (up to ipage-1).
        if pagecount > 1:
            for ipage in range(2,pagecount+1):
                self.log("Fetching additional page %i..." % ipage)
                data = self.static_query_data.copy()
                data['qid'] = qid
                data['SID'] = self.SID
                data['page'] = ipage
                response = self._request(self.summaryurl + "?" + urllib.urlencode(data))
                if response == -1:
                    return article_data, ipage-1
                article_data += [self.parse_article_data(res) for res in self.find_results(response)]

        return article_data, pagecount

    query_for_title = lambda self, papers: self.query_for_field(papers, 'title', 'TI')
    query_for_doi   = lambda self, papers: self.query_for_field(papers, 'doi', 'DO')
    def query_for_field(self, papers, name_local, name_wok):
        """Perform a query for a single field, for several articles by stacking OR statements.

        Argument papers is the list of papers to search for, whereas name_local
        is the dictionary key of the field to use, and name_wok is the two-letter
        WoK code for that ID (for example, for title it is 'TI').
        """
        pairs = [(name_wok, p[name_local]) for p in papers if p[name_local]]
        data = self.create_query_data(pairs, operator="OR")
        return self._generic_query(data)

    def query_for_author_pair(self, author1, author2):
        """Perform a query for articles that contain two authors."""
        data = self.create_query_data([('AU', author1), ('AU', author2)])
        return self._generic_query(data)

    def create_query_data(self, fields, operator="AND"):
        """Create query data for POST request from fields dict, glued with and operator."""

        data = self.static_query_data.copy()
        data['action'] = 'search'
        data['SID'] = self.SID

        data['fieldCount'] = '%i' % len(fields)
        for i,f in enumerate(fields):
            data['value(select%i)' % (i+1)] = f[0]
            data['value(input%i)' % (i+1)] = f[1]
        for i in range(len(fields)-1):
            op = operator*(type(operator) is str) or operator[i]
            data['value(bool_%i_%i)' % (i+1, i+2)] = op

        return data

    def parse_article_data(self, soup):
        """Extract data about an article from the search results HTML fragment for that article."""

        parsed = {}
        filter_out = lambda p, key: { k : p[k] for k in p if k != key }

        # The title should be in the first <value> tag of the first <a> tag.
        try:
            value_tag = soup.findAll("a").pop(0).findAll("value")[0]
            parsed['title'] = ' '.join(value_tag.getText(separator=' ').split())
        except IndexError:
            parsed = filter_out(parsed, 'title')

        # The first author, volume, pages and year should all occur after a <span> element
        # with an appropriate text. The DOI also used to be parsable in this way, before V5.13.
        for i,span in enumerate(soup.findAll("span")):

            # Up to three authors are listed in a <div> element directly after a <span> element
            # with the appropriate trigger text.
            if span.text[:3] == "By:":
                try:
                    parsed['first_author'] = span.parent.text.strip("By:").split(";")[0]
                except IndexError:
                    parsed = filter_out(parser, 'first_author')

            # The voume is found in the next <span> element after the <span> element with the
            # appropriate trigger text. Sometimes the volumes contains the issue, too, for example
            # when it is a supplement (as in '18 Suppl 1'), in which case remove it.
            if span.text[:7] == "Volume:":
                try:
                    parsed['vol'] = soup.findAll("span")[i+1].text.lower()
                    if "suppl" in parsed['vol']:
                        parsed['vol'] = parsed['vol'].split('suppl')[0].strip()
                except IndexError:
                    parsed = filter_out(parsed, 'vol')

            # The page is also in a <span> after the triggering <span> element. Although typically
            # the article number is treated as the page number, Web of Knowledge labels them separately,
            # so we need to parse that separately.
            if span.text[:6] == "Pages:":
                try:
                    parsed['pages'] = soup.findAll("span")[i+1].text
                except IndexError:
                    parsed = filter_out(parsed, 'pages')
            if span.text[:15] == "Article Number:":
                try:
                    parsed['article number'] = soup.findAll("span")[i+1].text
                except IndexError:
                    parsed = filter_out(parsed, 'article number')

            # In the <span> contains the data, the year normally comes after a month, but sometimes
            # it precedes the month, so also try to take the first word if the last one fails,
            # and checking that the year has four digits also catches a minority of strange strings
            # out there. Furthermore, the date is usually space-separated, but occasionally it is
            # formatted ISO-like with parts separated by dashes.
            if span.text[:10] == "Published:":
                try:
                    parsed['year'] = int(soup.findAll("span")[i+1].text.split()[-1].split()[-1])
                    assert len(str( parsed['year'])) == 4
                except (AssertionError, IndexError, ValueError):
                    try:
                        parsed['year'] = int(soup.findAll("span")[i+1].text.split()[0].split('-')[0])
                        assert len(str(parsed['year'])) == 4
                    except (AssertionError, IndexError, ValueError):
                        parsed = filter_out(parsed, 'year')

        # The times cited number is a bit different, and should be in a <div> with a specific class,
        # making it easy to find (as of V5.13). Perform several specific asserts to make sure
        # we have fished out the correct HTML element, thhough. Also, remember to remove commas
        # in the parsed text when the count goes above 999.
        data_cite = soup.findAll("div", { "class" : "search-results-data-cite" })
        try:
            assert len(data_cite) == 1
            assert data_cite[0].text[:12] == "Times Cited:"
            assert "from All Databases" in data_cite[0].text
            parsed['times_cited'] = int(data_cite[0].text[12:].split("(")[0].replace(",",""))
        except (AssertionError, IndexError, ValueError):
            parsed = filter_out(parsed, "times_cited")

        return parsed
