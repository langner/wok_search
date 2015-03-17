Automating Web of Science/Knowledge searches
============================================

Here are three ways to query Web of Science/Knowledge. Automating GET request like in wok-search.py is the easiest to handle, but the API used in wos-lamr.py is always the fastest if the Web of Science subset is sufficient. The SOAP appraoch in wos-soap.py is a fork from [the gist domoritz/wos.php](https://gist.github.com/domoritz/2012629) I tested, with slight modifications.

Here is an example of using the searcher class to fetch information about articles by author pair:
```python
>>> from wok_search import WebOfKnowledgeSearcher
>>> searcher = WebOfKnowledgeSearcher()
>>> result = searcher.query_for_author_pair("Einstein", "Schrodinger")
>>> print a[0][0]['title']
THE FREEDOM OF LEARNING.
>>> print a[0][0]
{'title': u'THE FREEDOM OF LEARNING.', 'first_author': u'Einstein, A', 'times_cited': 1, 'vol': u'83', 'year': 1936, 'pages': u'372-3'}
```

Note: **this is NOT a general purpose tool**. The code is quite robust, but the intent is only to provide some core functionality for other tools that search these literature resources. It was developed with only one such specific application in mind, and therefore may not be adequate in other cases in its current form. See the source for details about the data structures used and other query methods.
