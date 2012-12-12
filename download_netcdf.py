"""
InaSAFE Disaster risk assessment tool developed by AusAid and World Bank
- **Ftp Client for Retrieving ftp data.**

Contact : ole.moller.nielsen@gmail.com

.. note:: This program is free software; you can redistribute it and/or modify
     it under the terms of the GNU General Public License as published by
     the Free Software Foundation; either version 2 of the License, or
     (at your option) any later version.

"""
__author__ = 'imajimatika@gmail.com'
__version__ = '0.5.0'
__date__ = '19/07/2012'
__copyright__ = ('Copyright 2012, Australia Indonesia Facility for '
                 'Disaster Reduction')

import urllib2
import os
from BeautifulSoup import BeautifulSoup
netcdf_url = 'http://bfews.pusair-pu.go.id/Sobek-Floodmaps/'
download_directory = '/home/sunnii/Documents/inasafe/inasafe_real_flood' \
                     '/forecasting_data/'


def _read_contents(url):
    """Read contents of the url.
    Auxiliary function to read and return file urls.
    Args:
        * url = URL where the file is published
    Returns:
        * list of filename that can be used directly, e.g. with wget
            after concat it with netcdf_url
    """

    fid = urllib2.urlopen(url)
    html = fid.read()
    soup = BeautifulSoup(html)
    soup_table = soup.findAll('table')[0]
    soup_row = soup_table.findAll('tr')
    list_cell = []
    for row in soup_row:
        if len(row.findAll('td')) > 0:
            list_cell.append(row.findAll('td')[1])
    # get cell contains a tag
    list_inner_cells = []
    for cell in list_cell:
        if (len(cell.findAll('a')[0])) > 0:
            list_inner_cells.append(cell.findAll('a')[0])
    # get href
    list_name = []
    for inner_cell in list_inner_cells:
        if inner_cell.has_key('href'):
            list_name.append(inner_cell['href'])

    return list_name

def download_file_url(url, download_directory='', name=None):
    """Download file for one file
        * Args:
            - url : URL where the file is published
            - name : Optional parameter to select one file.
                    If omitted, latest file will be used.
        *Returns:
            - Instance of file containing name
    """

    # checking file in url directory
    names = _read_contents(url)
    if name is None:
        name = names[-1]
        print 'Getting file for latest file, which is %s' % name
    elif name not in names:
        print 'Can not download %s. File is not exist in %s' %\
              (name, url)
        return False
    else:
        print 'Getting file for selected file, which is %s' % name

    local_file_path = os.path.join(download_directory, name)

    # check local file, if exist, don't download
    if os.path.isfile(local_file_path):
        print 'But, file is exist, so use your local file.'
        return str(local_file_path)

    # directory management
    cwd = os.getcwd()
    os.chdir(download_directory)

    # download
    cmd = 'wget %s' % (url + name)
    print cmd
    os.system(cmd)

    # make sure the file has been downloaded
    if os.path.isfile(local_file_path):
        print 'file has been downloaded to %s' %\
              os.path.join(download_directory, name)
        retval = local_file_path
    else:
        print 'wow, file is not downloaded'
        retval = False

    os.chdir(cwd)
    return str(retval)

if __name__ == '__main__':
#    urls = _read_contents(netcdf_url)
#    print len(urls)
    download_file_url(netcdf_url, download_directory=download_directory)
    print 'fin'

