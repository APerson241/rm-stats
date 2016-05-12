#!/usr/bin/env python

import cgitb; cgitb.enable()

import cgi
import datetime
import itertools
import mwclient
import re
import sys
import urllib

DEFAULT_MAX_PAGES = 50
MAXIMUM_MAX_PAGES = 10000
TITLES_PER_REQUEST = 50
EN_WP = "en.wikipedia.org"
USER_AGENT = "RM Stats. Run by User:APerson. Using mwclient 0.8.1"

SIGNATURE_REGEX = r"(?:(?:\{\{unsigned.*?\}\})|(?:class=\"autosigned\")|(?:\[\[User.*?\]\].*?\(UTC\)))"
VOTE = re.compile(r"'''(.*?)'''.*?" + SIGNATURE_REGEX,
                   flags=re.IGNORECASE)
USERNAME = re.compile(r"\[\[User.*?:(.*?)(?:\||(?:\]\]))",
                  flags=re.IGNORECASE)
TIMESTAMP = re.compile(r"\d{2}:\d{2}, \d{1,2} [A-Za-z]* \d{4} \(UTC\)")
RESULT = re.compile("The\s+result\s+of\s+the\s+move\s+request\s+was(?:.*?)'''(.*?)'''.*?", flags=re.IGNORECASE)

NON_DISPLAYED_VOTES = ("note", "comment", "question")

def main():
    print_header()
    form = cgi.FieldStorage()
    username = form.getvalue("username")
    if not username:
        error_and_exit("Error! No username specified.")

    if form.getvalue("max"):
        try:
            max_pages = min(int(form.getvalue("max")), MAXIMUM_MAX_PAGES)
        except ValueError:
            max_pages = DEFAULT_MAX_PAGES
    else:
        print("Assuming that you want the most recent {} pages.".format(DEFAULT_MAX_PAGES))
        max_pages = DEFAULT_MAX_PAGES

    print("""<h1>RM Stats for %s</h1><div id="stats">""" % username)
    try:
        print_stats(username, max_pages)
    except ValueError as e:
        error_and_exit("Error! Unable to calculate statistics. " + str(e) + " You may have misspelled that username.")
    print("</div>")
    print_footer()

def print_header():
    print("Content-Type: text/html")
    print
    print("""
    <!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8" />
    <title>RM Stats Results</title>
    <link href="../assets/css/style.css" rel="stylesheet" />
    <link href="../assets/css/results.css" rel="stylesheet" />
    </head>
    <body><p><a href="../index.html">&larr; New search</a></p>""")

def error_and_exit(error):
    print("""<p class="error">%s</p>""" % error)
    print_footer()
    sys.exit(0)

def print_footer():
    print("""
<p><a href="../index.html">&larr; New search</a></p>
<footer>
  <a href="https://en.wikipedia.org/wiki/User:APerson" title="APerson's user page on the English Wikipedia">APerson</a> (<a href="https://en.wikipedia.org/wiki/User_talk:APerson" title="APerson's talk page on the English Wikipedia">talk!</a>) &middot; <a href="https://github.com/APerson241/rm-stats" title="Source code on GitHub">Source code</a> &middot; <a href="https://github.com/APerson241/rm-stats/issues" title="Issues on GitHub">Issues</a>
</footer>
</body>
</html>""")

def print_stats(username, max_pages):
    texts = get_wikitexts(username, max_pages)

    # We only want texts with requested moves
    texts = {x: y for x, y in texts.items() if "requested move" in y.lower()}
    if not texts:
        error_and_exit("I couldn't find any requested-move participation for {}.".format(username))

    votes = [] # (wikilink, vote, timestamp)
    for title, text in texts.items():
        fragments = text.split("==")[1:]
        for i in xrange(0, len(fragments), 2):
            try:
                heading, body = fragments[i:i+2]
            except ValueError:
                print("<p>Note: I wasn't able to parse <a href='https://en.wikipedia.org/wiki/{}'>{}</a> because of an error in a section header.</p>".format(urllib.quote(title.encode("utf-8")), title.encode("utf-8")))
                continue

            if "requested move" not in body:
                continue

            result_search = RESULT.search(body)
            if result_search:
                close = result_search.group(1)
            else:
                close = "Not closed yet"

            for each_match in VOTE.finditer(body):
                match_text = each_match.group(0)
                vote = each_match.group(1)

                username_search = USERNAME.search(match_text)
                if username_search:
                    each_username = username_search.groups()[-1].strip()
                else:
                    each_username = ""

                if each_username and each_username.lower() in vote.lower():
                    # For users with signatures that have bolded text
                    continue

                time = get_timestamp(match_text)

                if username == each_username:
                    votes.append((title + "#" + heading.strip(), time, vote, close))

    # Actually do the printing
    print("<table class='votes'><tr><th>Page</th><th>Timestamp</th><th>Vote</th><th>Close</th></tr>")
    votes.sort(key=lambda x:x[1], reverse=True)
    votes = [x for x in votes if not any(y in x[2].lower() for y in NON_DISPLAYED_VOTES)]
    for discussion, timestamp, vote, close in votes:
        title = discussion.split("#")[0]
        print("<tr><td class='title'><a href='https://en.wikipedia.org/wiki/%s'>%s</a></td><td>%s</td><td>%s</td><td>%s</td></tr>" % (urllib.quote(discussion.encode("utf-8")), title.encode("utf-8"), datetime.datetime.strftime(timestamp, "%-d %B %Y"), vote.encode("utf-8").capitalize().replace(".", ""), close.encode("utf-8").capitalize().replace(".", "")))
    print("</table>")

def get_contributions(site, username, num_contributions):
    """Get a list of talk-namespace contributions."""
    result = []
    gen = site.usercontributions(username, namespace=1)
    for contrib in itertools.islice(gen, num_contributions):
        result.append(contrib)
    return result

def get_wikitexts(username, max_pages):
    site = mwclient.Site(EN_WP, clients_useragent=USER_AGENT)

    # Get the wikitexts of each page
    print("<p>Scanned <a href='https://en.wikipedia.org/wiki/User:{0}'>{0}</a>'s {1} most recent talk-namespace contributions.</p>".format(username, max_pages))
    contributions = get_contributions(site, username, max_pages)
    if not contributions:
        raise ValueError("No contributions for %s found." % username)
    #contributions = get_contributions_from_file(site, username)
    titles = list(set(x["title"] for x in contributions))
    if not titles:
        raise ValueError("No talk-space contributions for %s found." % username)
    wikitexts = get_texts(site, titles)
    return wikitexts

def get_texts(site, titles):
    """Given a list of titles, get the full text of each page edited."""
    result = {}

    # ["a", "b", "c", ..., "z", "aa", "bb", ...] -> ["a|b|c|...", "z|aa|bb|..."]
    titles_strings = []
    if len(titles) > TITLES_PER_REQUEST:
        for index in xrange(0, len(titles) - 1, TITLES_PER_REQUEST):
            titles_string = ""
            for title in titles[index:min(len(titles) - 1, index + TITLES_PER_REQUEST)]:
                titles_string += title + "|"
            titles_strings.append(titles_string[:-1])
    else:
        titles_strings = ["|".join(titles)]

    for titles_string in titles_strings:
        continue_params = {"continue":""}
        while True:
            api_result = site.api("query", prop="revisions", rvprop="content", titles=titles_string, **continue_params)
            if "pages" not in api_result["query"]:
                print(api_result)
            for page_dict in api_result["query"]["pages"].values():
                result[page_dict["title"]] = page_dict["revisions"][0]["*"]
            if "continue" in api_result:
                continue_params = api_result["continue"]
            else:
                break
    return result

def get_timestamp(wikitext):
    """Gets the first timestamp from the given wikitext."""
    time_search = TIMESTAMP.search(wikitext)
    if time_search:
        try:
            time_string = time_search.group(0).replace("(UTC)", "").strip()
            return datetime.datetime.strptime(time_string, "%H:%M, %d %B %Y")
        except ValueError:
            return ""
    else:
        return ""

main()
