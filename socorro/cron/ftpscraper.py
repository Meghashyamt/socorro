#! /usr/bin/env python
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
ftpscraper.py pulls build information from ftp.mozilla.org for
nightly and release builds.
"""
import logging
import urllib2
import lxml.html
import datetime

import socorro.lib.buildutil as buildutil
import socorro.lib.psycopghelper as psy
import socorro.lib.util as util

logger = logging.getLogger("ftpscraper")


def getLinks(url, startswith=None, endswith=None, urllib=urllib2):
    page = urllib.urlopen(url)
    html = lxml.html.document_fromstring(page.read())
    page.close()

    results = []
    for element, attribute, link, pos in html.iterlinks():
        if startswith:
            if link.startswith(startswith):
                results.append(link)
        elif endswith:
            if link.endswith(endswith):
                results.append(link)
    return results


def parseInfoFile(url, nightly=False, urllib=urllib2):
    infotxt = urllib.urlopen(url)
    contents = infotxt.read().split()
    infotxt.close()
    results = {}
    if nightly:
        results = {'buildID': contents[0], 'rev': contents[1]}
        if len(contents) > 2:
            results['altrev'] = contents[2]
    else:
        for entry in contents:
            (k, v) = entry.split('=')
            results[k] = v

    return results


def getRelease(dirname, url, urllib=urllib2):
    candidate_url = '%s/%s' % (url, dirname)
    builds = getLinks(candidate_url, startswith='build', urllib=urllib)
    if not builds:
        logger.info('No build dirs in %s' % candidate_url)
        return

    latest_build = builds.pop()
    build_url = '%s/%s' % (candidate_url, latest_build)

    info_files = getLinks(build_url, endswith='_info.txt', urllib=urllib)

    for f in info_files:
        info_url = '%s/%s' % (build_url, f)
        kvpairs = parseInfoFile(info_url)

        platform = f.split('_info.txt')[0]

        version = dirname.split('-candidates')[0]
        build_number = latest_build.strip('/')

        yield (platform, version, build_number, kvpairs)


def getNightly(dirname, url, urllib=urllib2, backfill_date=None):
    nightly_url = '%s/%s' % (url, dirname)

    info_files = getLinks(nightly_url, endswith='.txt', urllib=urllib)
    for f in info_files:
        pv = None
        platform = None
        if 'en-US' in f:
            (pv, platform) = f.strip('.txt').split('.en-US.')
        elif 'multi' in f:
            (pv, platform) = f.strip('.txt').split('.multi.')
        else:
            return

        version = pv.split('-')[-1]
        repository = []

        for field in dirname.split('-'):
            if not field.isdigit():
                repository.append(field)
        repository = '-'.join(repository).strip('/')

        info_url = '%s/%s' % (nightly_url, f)
        kvpairs = parseInfoFile(info_url, nightly=True)

        yield (platform, repository, version, kvpairs)


def recordBuilds(config, backfill_date):
    databaseConnectionPool = psy.DatabaseConnectionPool(config.databaseHost,
      config.databaseName, config.databaseUserName, config.databasePassword,
      logger)

    try:
        connection, cursor = databaseConnectionPool.connectionCursorPair()
        for product_name in config.products:

            scrapeReleases(config, cursor, product_name)

            today = datetime.datetime.today()
            if backfill_date is not None:
                currentdate = backfill_date
                while currentdate <= today:
                    logger.debug('backfilling for date ' + str(currentdate))
                    scrapeNightlies(config, cursor, product_name,
                                    date=currentdate)
                    currentdate += datetime.timedelta(days=1)
            else:
                scrapeNightlies(config, cursor, product_name, date=today)
    finally:
        databaseConnectionPool.cleanup()


def scrapeReleases(config, cursor, product_name, urllib=urllib2):
    prod_url = '%s/%s/' % (config.base_url, product_name)

    # releases are sometimes in nightly, sometimes in candidates dir.
    # look in both.
    for directory in ('nightly', 'candidates'):
        if not getLinks(prod_url, startswith=directory, urllib=urllib):
            logger.debug('Dir %s not found for %s' % (directory, product_name))
            continue

        url = '%s/%s/%s/' % (config.base_url, product_name, directory)

        try:
            releases = getLinks(url, endswith='-candidates/',
                                urllib=urllib)
            for release in releases:
                for info in getRelease(release, url):
                    (platform, version, build_number, kvpairs) = info
                    build_type = 'Release'
                    beta_number = None
                    repository = 'mozilla-release'
                    if 'b' in version:
                        build_type = 'Beta'
                        version, beta_number = version.split('b')
                        repository = 'mozilla-beta'
                    build_id = kvpairs['buildID']
                    buildutil.insert_build(cursor, product_name, version,
                                           platform, build_id, build_type,
                                           beta_number, repository,
                                           ignore_duplicates=True)
        except urllib.URLError:
            util.reportExceptionAndContinue(logger)


def scrapeNightlies(config, cursor, product_name, urllib=urllib2, date=None):
    month = date.strftime('%m')
    nightly_url = '%s/%s/%s/%s/%s/' % (config.base_url, product_name,
                       'nightly', date.year, month)

    try:

        day = date.strftime('%d')
        dir_prefix = '%s-%s-%s' % (date.year, month, day)
        nightlies = getLinks(nightly_url, startswith=dir_prefix,
                 urllib=urllib)
        for nightly in nightlies:
            for info in getNightly(nightly, nightly_url):
                (platform, repository, version, kvpairs) = info
                build_id = kvpairs['buildID']
                build_type = 'Nightly'
                if version.endswith('a2'):
                    build_type = 'Aurora'
                buildutil.insert_build(cursor, product_name, version, platform,
                                       build_id, build_type, None, repository,
                                       ignore_duplicates=True)

    except urllib.URLError:
        util.reportExceptionAndContinue(logger)
