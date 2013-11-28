# -*- coding: utf-8 -*-
"""
InaSAFE Disaster risk assessment tool developed by AusAid and World Bank
- **Functionality related to shake events.**

Contact : ole.moller.nielsen@gmail.com

.. note:: This program is free software; you can redistribute it and/or modify
     it under the terms of the GNU General Public License as published by
     the Free Software Foundation; either version 2 of the License, or
     (at your option) any later version.

"""

__author__ = 'tim@linfiniti.com'
__version__ = '0.5.0'
__date__ = '1/08/2012'
__copyright__ = ('Copyright 2012, Australia Indonesia Facility for '
                 'Disaster Reduction')

import os
import sys
import shutil
import cPickle as pickle
from xml.dom import minidom
import math
from subprocess import call, CalledProcessError
import logging
from datetime import datetime

import numpy
import pytz  # sudo apt-get install python-tz
import ogr
import gdal
from gdalconst import GA_ReadOnly

from sftp_shake_data import SftpShakeData


# TODO I think QCoreApplication is needed for tr() check hefore removing
from PyQt4.QtCore import (
    QCoreApplication,
    QObject,
    QVariant,
    QFileInfo,
    QString,
    QStringList,
    QUrl,
    QSize,
    Qt,
    QTranslator)
from PyQt4.QtXml import QDomDocument
# We should remove the following pylint suppressions when we support only QGIS2
# pylint: disable=E0611
# pylint: disable=W0611
# Above for pallabelling
from qgis.core import (
    QgsPoint,
    QgsField,
    QgsFeature,
    QgsGeometry,
    QgsVectorLayer,
    QgsRaster,
    QgsRasterLayer,
    QgsRectangle,
    QgsDataSourceURI,
    QgsVectorFileWriter,
    QgsCoordinateReferenceSystem,
    QgsProject,
    QgsComposition,
    QgsMapLayerRegistry,
    QgsMapRenderer,
    QgsPalLabeling,
    QgsProviderRegistry,
    QgsFeatureRequest)
# pylint: enable=E0611
# pylint: enable=W0611
from safe_qgis.utilities.utilities_for_testing import get_qgis_app
from safe_qgis.exceptions import TranslationLoadError
from safe.common.version import get_version
from safe.api import get_plugins as safe_get_plugins
from safe.api import read_layer as safe_read_layer
from safe.api import calculate_impact as safe_calculate_impact
from safe.api import Table, TableCell, TableRow
from safe_qgis.utilities.utilities import get_wgs84_resolution
from safe_qgis.utilities.clipper import extent_to_geoarray, clip_layer
from safe_qgis.utilities.styling import mmi_colour
from utils import shakemapExtractDir, dataDir
from rt_exceptions import (
    GridXmlFileNotFoundError,
    GridXmlParseError,
    ContourCreationError,
    InvalidLayerError,
    ShapefileCreationError,
    CityMemoryLayerCreationError,
    FileNotFoundError,
    MapComposerError)
from realtime.utils import setupLogger
# from shake_data import ShakeData

setupLogger()
LOGGER = logging.getLogger('InaSAFE')
QGIS_APP, CANVAS, IFACE, PARENT = get_qgis_app()


class ShakeEvent(QObject):
    """The ShakeEvent class encapsulates behaviour and data relating to an
    earthquake, including epicenter, magnitude etc."""

    def __init__(self,
                 theEventId=None,
                 theLocale='en',
                 thePopulationRasterPath=None,
                 theForceFlag=False,
                 theDataIsLocalFlag=False):
        """Constructor for the shake event class.

        Args:
            * theEventId - (Optional) Id of the event. Will be used to
                fetch the ShakeData for this event (either from cache or from
                ftp server as required). The grid.xml file in the unpacked
                event will be used to intialise the state of the ShakeEvent
                instance.
                If no event id is supplied, the most recent event recorded
                on the server will be used.
            * theLocale - (Optional) string for iso locale to use for outputs.
                Defaults to en. Can also use 'id' or possibly more as
                translations are added.
            * thePopulationRasterPath - (Optional)path to the population raster
                that will be used if you want to calculate the impact. This
                is optional because there are various ways this can be
                specified before calling :func:`calculate_impacts`.
            * theForceFlag: bool Whether to force retrieval of the dataset from
                the ftp server.
            * theDataIsLocalFlag: bool Whether the data is already extracted
                and exists locally. Use this in cases where you manually want
                to run a grid.xml without first doing a download.

        Returns: Instance

        Raises: EventXmlParseError
        """
        # We inherit from QObject for translation support
        QObject.__init__(self)

        self.check_environment()

        if theDataIsLocalFlag:
            self.eventId = theEventId
        else:
            # fetch the data from (s)ftp
            #self.data = ShakeData(theEventId, theForceFlag)
            self.data = SftpShakeData(
                theEvent=theEventId,
                theForceFlag=theForceFlag)
            self.data.extract()
            self.eventId = self.data.eventId

        self.latitude = None
        self.longitude = None
        self.magnitude = None
        self.depth = None
        self.description = None
        self.location = None
        self.day = None
        self.month = None
        self.year = None
        self.time = None
        self.hour = None
        self.minute = None
        self.second = None
        self.timezone = None
        self.x_minimum = None
        self.x_maximum = None
        self.y_minimum = None
        self.y_maximum = None
        self.rows = None
        self.columns = None
        self.mmi_data = None
        self.populationRasterPath = thePopulationRasterPath
        # Path to tif of impact result - probably we wont even use it
        self.impact_file = None
        # Path to impact keywords file - this is GOLD here!
        self.impact_keywords_file = None
        # number of people killed per mmi band
        self.fatality_counts = None
        # Total number of predicted fatalities
        self.fatality_total = 0
        # number of people displaced per mmi band
        self.displaced_counts = None
        # number of people affected per mmi band
        self.affected_counts = None
        # After selecting affected cities near the event, the bbox of
        # shake map + cities
        self.extent_with_cities = None
        # How much to iteratively zoom out by when searching for cities
        self.zoomFactor = 1.25
        # The search boxes used to find extent_with_cities
        # Stored in the form [{'city_count': int, 'geometry': QgsRectangle()}]
        self.search_boxes = None
        # Stored as a dict with dir_to, dist_to,  dist_from etc e.g.
        #{'dir_from': 16.94407844543457,
        #'dir_to': -163.05592346191406,
        #'roman': 'II',
        #'dist_to': 2.504295825958252,
        #'mmi': 1.909999966621399,
        #'name': 'Tondano',
        #'id': 57,
        #'population': 33317}
        self.most_affected_city = None
        # for localization
        self.translator = None
        self.locale = theLocale
        self.setupI18n()
        self.parse_grid_xml()

    def check_environment(self):
        """A helper class to check that QGIS is correctly initialised.

        :raises: EnvironmentError if the environment is not correct.
        """
        # noinspection PyArgumentList
        registry = QgsProviderRegistry.instance()
        registry_list = registry.pluginList()
        if len(registry_list) < 1:
            raise EnvironmentError('QGIS data provider list is empty!')

    def grid_file_path(self):
        """A helper to retrieve the path to the grid.xml file

        :return: An absolute filesystem path to the grid.xml file.
        :raise: GridXmlFileNotFoundError
        """
        LOGGER.debug('Event path requested.')
        grid_xml_path = os.path.join(shakemapExtractDir(),
                                     self.eventId,
                                     'grid.xml')
        #short circuit if the tif is already created.
        if os.path.exists(grid_xml_path):
            return grid_xml_path
        else:
            LOGGER.error('Event file not found. %s' % grid_xml_path)
            raise GridXmlFileNotFoundError('%s not found' % grid_xml_path)

    def extract_datetime(self, timestamp):
        """Extract the parts of a date given a timestamp as per below example.

        :param timestamp: (str) as provided by the 'event_timestamp'
                attribute in the grid.xml.

        # now separate out its parts
        # >>> e = "2012-08-07T01:55:12WIB"
        #>>> e[0:10]
        #'2012-08-07'
        #>>> e[12:-3]
        #'01:55:11'
        #>>> e[-3:]
        #'WIB'   (WIB = Western Indonesian Time)
        """
        date_tokens = timestamp[0:10].split('-')
        self.year = int(date_tokens[0])
        self.month = int(date_tokens[1])
        self.day = int(date_tokens[2])
        time_tokens = timestamp[11:-3].split(':')
        self.hour = int(time_tokens[0])
        self.minute = int(time_tokens[1])
        self.second = int(time_tokens[2])

    def parse_grid_xml(self):
        """Parse the grid xyz and calculate the bounding box of the event.

        :raise GridXmlParseError

        The grid xyz dataset looks like this::

           <?xml version="1.0" encoding="US-ASCII" standalone="yes"?>
           <shakemap_grid xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
           xmlns="http://earthquake.usgs.gov/eqcenter/shakemap"
           xsi:schemaLocation="http://earthquake.usgs.gov
           http://earthquake.usgs.gov/eqcenter/shakemap/xml/schemas/
           shakemap.xsd" event_id="20120807015938" shakemap_id="20120807015938"
           shakemap_version="1" code_version="3.5"
           process_timestamp="2012-08-06T18:28:37Z" shakemap_originator="us"
           map_status="RELEASED" shakemap_event_type="ACTUAL">
           <event magnitude="5.1" depth="206" lat="2.800000"
               lon="128.290000" event_timestamp="2012-08-07T01:55:12WIB"
               event_network="" event_description="Halmahera, Indonesia    " />
           <grid_specification lon_min="126.290000" lat_min="0.802000"
               lon_max="130.290000" lat_max="4.798000"
               nominal_lon_spacing="0.025000" nominal_lat_spacing="0.024975"
               nlon="161" nlat="161" />
           <grid_field index="1" name="LON" units="dd" />
           <grid_field index="2" name="LAT" units="dd" />
           <grid_field index="3" name="PGA" units="pctg" />
           <grid_field index="4" name="PGV" units="cms" />
           <grid_field index="5" name="MMI" units="intensity" />
           <grid_field index="6" name="PSA03" units="pctg" />
           <grid_field index="7" name="PSA10" units="pctg" />
           <grid_field index="8" name="PSA30" units="pctg" />
           <grid_field index="9" name="STDPGA" units="pctg" />
           <grid_field index="10" name="URAT" units="" />
           <grid_field index="11" name="SVEL" units="ms" />
           <grid_data>
           126.2900 04.7980 0.01 0.02 1.16 0.05 0.02 0 0.5 1 600
           126.3150 04.7980 0.01 0.02 1.16 0.05 0.02 0 0.5 1 600
           126.3400 04.7980 0.01 0.02 1.17 0.05 0.02 0 0.5 1 600
           126.3650 04.7980 0.01 0.02 1.17 0.05 0.02 0 0.5 1 600
           ...
           ... etc

        .. note:: We could have also obtained some of this data from the
           grid.xyz and event.xml but the **grid.xml** is preferred because it
           contains clear and unequivical metadata describing the various
           fields and attributes. Also it provides all the data we need in a
           single file.
        """
        LOGGER.debug('ParseGridXml requested.')
        path = self.grid_file_path()
        try:
            document = minidom.parse(path)
            event_element = document.getElementsByTagName('event')
            event_element = event_element[0]
            self.magnitude = float(
                event_element.attributes['magnitude'].nodeValue)
            self.longitude = float(
                event_element.attributes['lon'].nodeValue)
            self.latitude = float(
                event_element.attributes['lat'].nodeValue)
            self.location = event_element.attributes[
                'event_description'].nodeValue.strip()
            self.depth = float(event_element.attributes['depth'].nodeValue)
            # Get the date - its going to look something like this:
            # 2012-08-07T01:55:12WIB
            timestamp = event_element.attributes['event_timestamp'].nodeValue
            self.extract_datetime(timestamp)
            # Note the timezone here is inconsistent with YZ from grid.xml
            # use the latter
            self.timezone = timestamp[-3:]

            specification_element = document.getElementsByTagName(
                'grid_specification')
            specification_element = specification_element[0]
            self.x_minimum = float(
                specification_element.attributes['lon_min'].nodeValue)
            self.x_maximum = float(
                specification_element.attributes['lon_max'].nodeValue)
            self.y_minimum = float(
                specification_element.attributes['lat_min'].nodeValue)
            self.y_maximum = float(
                specification_element.attributes['lat_max'].nodeValue)
            self.rows = float(
                specification_element.attributes['nlat'].nodeValue)
            self.columns = float(
                specification_element.attributes['nlon'].nodeValue)
            data_element = document.getElementsByTagName('grid_data')
            data_element = data_element[0]
            data = data_element.firstChild.nodeValue

            # Extract the 1,2 and 5th (MMI) columns and populate mmi_data
            lon_column = 0
            lat_column = 1
            mmi_column = 4
            self.mmi_data = []
            for line in data.split('\n'):
                if not line:
                    continue
                tokens = line.split(' ')
                lon = tokens[lon_column]
                lat = tokens[lat_column]
                mmi = tokens[mmi_column]
                datum_tuple = (lon, lat, mmi)
                self.mmi_data.append(datum_tuple)

        except Exception, e:
            LOGGER.exception('Event parse failed')
            raise GridXmlParseError(
                'Failed to parse grid file.\n%s\n%s'
                % (e.__class__, str(e)))

    def mmi_data_to_delimited_text(self):
        """Return the mmi data as a delimited test string.

        :return: a delimited text string that can easily be written to
            disk for e.g. use by gdal_grid.
        :rtype:  str

        The returned string will look like this::

           123.0750,01.7900,1
           123.1000,01.7900,1.14
           123.1250,01.7900,1.15
           123.1500,01.7900,1.16
           etc...
        """
        string = 'lon,lat,mmi\n'
        for row in self.mmi_data:
            string += '%s,%s,%s\n' % (row[0], row[1], row[2])
        return string

    def mmi_data_to_delimited_file(self, force_flag=True):
        """Save the mmi_data to a delimited text file suitable for processing
        with gdal_grid.

        :param force_flag: Optional. Whether to force the regeneration of the
        output file. Defaults to False.
        :type force_flag: bool
        :return: The absolute file system path to the delimited text file.
        :rtype: str

        The output file will be of the same format as strings returned from
        :func:`mmi_to_delimited_text`.

        .. note:: An accompanying .csvt will be created which gdal uses to
           determine field types. The csvt will contain the following string:
           "Real","Real","Real". These types will be used in other conversion
           operations. For example to convert the csv to a shp you would do::

              ogr2ogr -select mmi -a_srs EPSG:4326 mmi.shp mmi.vrt mmi
        """
        LOGGER.debug('mmi_to_delimited_text requested.')

        path = os.path.join(shakemapExtractDir(),
                            self.eventId,
                            'mmi.csv')
        #short circuit if the csv is already created.
        if os.path.exists(path) and force_flag is not True:
            return path
        result_file = file(path, 'wt')
        result_file.write(self.mmi_data_to_delimited_text())
        result_file.close()

        # Also write the .csv which contains metadata about field types
        csv_path = os.path.join(
            shakemapExtractDir(), self.eventId, 'mmi.csvt')
        result_file = file(csv_path, 'wt')
        result_file.write('"Real","Real","Real"')
        result_file.close()
        return path

    def mmi_data_to_vrt(self, force_flag=True):
        """Save the mmi_data to an ogr vrt text file.

        :param force_flag: Optional. Whether to force the regeneration
            of the output file. Defaults to False.
        :type force_flag: bool
        :return: The absolute file system path to the .vrt text file.
        :rtype: str
        :raises: None

        """
        # Ensure the delimited mmi file exists
        LOGGER.debug('mmi_to_vrt requested.')

        vrt_path = os.path.join(shakemapExtractDir(),
                                self.eventId,
                                'mmi.vrt')

        #short circuit if the vrt is already created.
        if os.path.exists(vrt_path) and force_flag is not True:
            return vrt_path

        csv_path = self.mmi_data_to_delimited_file(force_flag)

        vrt_string = ('<OGRVRTDataSource>'
                      '  <OGRVRTLayer name="mmi">'
                      '    <SrcDataSource>%s</SrcDataSource>'
                      '    <GeometryType>wkbPoint</GeometryType>'
                      '    <GeometryField encoding="PointFromColumns"'
                      '                      x="lon" y="lat" z="mmi"/>'
                      '  </OGRVRTLayer>'
                      '</OGRVRTDataSource>' % csv_path)
        result_file = file(vrt_path, 'wt')
        result_file.write(vrt_string)
        result_file.close()
        return vrt_path

    def _add_executable_prefix(self, command):
        """Add the executable prefix for gdal binaries.

        This is primarily needed for OSX where gdal tools are tucked away in
        the Library path.
        :param command: A string containing the command to
        which the prefix will be prepended
        :type command: str
        :return: A copy of the command with the prefix added.
        :rtype: str
        :raises: None
        """

        executable_prefix = ''
        if sys.platform == 'darwin':  # Mac OS X
            # .. todo:: FIXME - softcode gdal version in this path
            executable_prefix = ('/Library/Frameworks/GDAL.framework/'
                                 'Versions/1.9/Programs/')
        command = executable_prefix + command
        return command

    def _run_command(self, command):
        """Run a command and raise any error as needed.

        This is a simple runner for executing gdal commands.

        :param command: Required. A command string to be run.
        :type command: str
        :returns: None
        :raises: Any exceptions will be propagated.
        """

        the_command = self._add_executable_prefix(command)

        try:
            result = call(the_command, shell=True)
            del result
        except CalledProcessError, e:
            LOGGER.exception('Running command failed %s' % the_command)
            message = ('Error while executing the following shell '
                       'command: %s\nError message: %s'
                       % (the_command, str(e)))
            # shameless hack - see https://github.com/AIFDR/inasafe/issues/141
            if sys.platform == 'darwin':  # Mac OS X
                if 'Errno 4' in str(e):
                    # continue as the error seems to be non critical
                    pass
                else:
                    raise Exception(message)
            else:
                raise Exception(message)

    def mmi_data_to_shapefile(self, force_flag=False):
        """Convert grid.xml's mmi column to a vector shp file using ogr2ogr.

        An ESRI shape file will be created.

        :param force_flag: bool (Optional). Whether to force the regeneration
            of the output file. Defaults to False.
        :return: Path to the resulting tif file.
        :rtype: str

        Example of the ogr2ogr call we generate::

           ogr2ogr -select mmi -a_srs EPSG:4326 mmi.shp mmi.vrt mmi

        .. note:: It is assumed that ogr2ogr is in your path.
        """
        LOGGER.debug('mmi_data_to_shapefile requested.')

        shp_path = os.path.join(shakemapExtractDir(),
                                self.eventId,
                                'mmi-points.shp')
        # Short circuit if the tif is already created.
        if os.path.exists(shp_path) and force_flag is not True:
            return shp_path

        # Ensure the vrt mmi file exists (it will generate csv too if needed)
        vrt_path = self.mmi_data_to_vrt(force_flag)

        #now generate the tif using default interpolation options

        the_command = (
            ('ogr2ogr -overwrite -select mmi -a_srs EPSG:4326 '
             '%(shp)s %(vrt)s mmi') % {'shp': shp_path, 'vrt': vrt_path})

        LOGGER.info('Created this gdal command:\n%s' % the_command)
        # Now run GDAL warp scottie...
        self._run_command(the_command)

        # Lastly copy over the standard qml (QGIS Style file) for the mmi.tif
        qml_path = os.path.join(shakemapExtractDir(),
                                self.eventId,
                                'mmi-points.qml')
        source_qml = os.path.join(dataDir(), 'mmi-shape.qml')
        shutil.copyfile(source_qml, qml_path)
        return shp_path

    def mmi_data_to_raster(self, force_flag=False, algorithm='nearest'):
        """Convert the grid.xml's mmi column to a raster using gdal_grid.

        A geotiff file will be created.

        Unfortunately no python bindings exist for doing this so we are
        going to do it using a shell call.

        :param force_flag: (Optional). Whether to force the regeneration
            of the output file. Defaults to False.
        :type force_flag: bool
        :param algorithm: (Optional). Which resampling algorithm to use.
            Valid options are 'nearest' (for nearest neighbour), 'invdist'
            (for inverse distance), 'average' (for moving average). Defaults
            to 'nearest' if not specified. Note that passing resampling alg
            parameters is currently not supported. If None is passed it will
            be replaced with 'nearest'.
        :type algorithm: str
        .. seealso:: http://www.gdal.org/gdal_grid.html

        :return: Path to the resulting tif file.
        :rtype: str

        :raises: None

        Example of the gdal_grid call we generate::

           gdal_grid -zfield "mmi" -a invdist:power=2.0:smoothing=1.0 \
           -txe 126.29 130.29 -tye 0.802 4.798 -outsize 400 400 -of GTiff \
           -ot Float16 -l mmi mmi.vrt mmi.tif

        .. note:: It is assumed that gdal_grid is in your path.

        .. note:: For interest you can also make quite beautiful smoothed
          rasters using this:

          gdal_grid -zfield "mmi" -a_srs EPSG:4326
          -a invdist:power=2.0:smoothing=1.0 -txe 122.45 126.45
          -tye -2.21 1.79 -outsize 400 400 -of GTiff
          -ot Float16 -l mmi mmi.vrt mmi-trippy.tif
        """
        LOGGER.debug('mmi_to_raster requested.')

        if algorithm is None:
            algorithm = 'nearest'

        tif_path = os.path.join(shakemapExtractDir(),
                                self.eventId,
                                'mmi-%s.tif' % algorithm)
        #short circuit if the tif is already created.
        if os.path.exists(tif_path) and force_flag is not True:
            return tif_path

        # Ensure the vrt mmi file exists (it will generate csv too if needed)
        vrt_path = self.mmi_data_to_vrt(force_flag)

        # now generate the tif using default nearest neighbour interpolation
        # options. This gives us the same output as the mi.grd generated by
        # the earthquake server.

        if 'invdist' in algorithm:
            the_algorithm = 'invdist:power=2.0:smoothing=1.0'
        else:
            the_algorithm = algorithm

        options = {
            'alg': the_algorithm,
            'xMin': self.x_minimum,
            'xMax': self.x_maximum,
            'yMin': self.y_minimum,
            'yMax': self.y_maximum,
            'dimX': self.columns,
            'dimY': self.rows,
            'vrt': vrt_path,
            'tif': tif_path}

        command = (('gdal_grid -a %(alg)s -zfield "mmi" -txe %(xMin)s '
                    '%(xMax)s -tye %(yMin)s %(yMax)s -outsize %(dimX)i '
                    '%(dimY)i -of GTiff -ot Float16 -a_srs EPSG:4326 -l mmi '
                    '%(vrt)s %(tif)s') % options)

        LOGGER.info('Created this gdal command:\n%s' % command)
        # Now run GDAL warp scottie...
        self._run_command(command)

        # copy the keywords file from fixtures for this layer
        keyword_path = os.path.join(
            shakemapExtractDir(),
            self.eventId,
            'mmi-%s.keywords' % algorithm)
        source_keywords = os.path.join(dataDir(), 'mmi.keywords')
        shutil.copyfile(source_keywords, keyword_path)
        # Lastly copy over the standard qml (QGIS Style file) for the mmi.tif
        qml_path = os.path.join(shakemapExtractDir(),
                                self.eventId,
                                'mmi-%s.qml' % algorithm)
        source_qml = os.path.join(dataDir(), 'mmi.qml')
        shutil.copyfile(source_qml, qml_path)
        return tif_path

    def mmi_data_to_contours(self, force_flag=True, algorithm='nearest'):
        """Extract contours from the event's tif file.

        Contours are extracted at a 0.5 MMI interval. The resulting file will
        be saved in the extract directory. In the easiest use case you can

        :param force_flag:  (Optional). Whether to force the
        regeneration of contour product. Defaults to False.
        :type force_flag: bool

        :param algorithm: (Optional) Which interpolation algorithm to
                  use to create the underlying raster. Defaults to 'nearest'.
        :type algorithm: str
        **Only enforced if theForceFlag is true!**

        :returns: An absolute filesystem path pointing to the generated
            contour dataset.
        :exception: ContourCreationError
        simply do::

           myShakeEvent = myShakeData.shakeEvent()
           myContourPath = myShakeEvent.mmiToContours()

        which will return the contour dataset for the latest event on the
        ftp server.
        """
        LOGGER.debug('mmi_data_to_contours requested.')
        # TODO: Use sqlite rather?
        output_file_base = os.path.join(shakemapExtractDir(),
                                        self.eventId,
                                        'mmi-contours-%s.' % algorithm)
        output_file = output_file_base + 'shp'
        if os.path.exists(output_file) and force_flag is not True:
            return output_file
        elif os.path.exists(output_file):
            try:
                os.remove(output_file_base + 'shp')
                os.remove(output_file_base + 'shx')
                os.remove(output_file_base + 'dbf')
                os.remove(output_file_base + 'prj')
            except OSError:
                LOGGER.exception(
                    'Old contour files not deleted'
                    ' - this may indicate a file permissions issue.')

        tif_path = self.mmi_data_to_raster(force_flag, algorithm)
        # Based largely on
        # http://svn.osgeo.org/gdal/trunk/autotest/alg/contour.py
        driver = ogr.GetDriverByName('ESRI Shapefile')
        ogr_dataset = driver.CreateDataSource(output_file)
        if ogr_dataset is None:
            # Probably the file existed and could not be overriden
            raise ContourCreationError('Could not create datasource for:\n%s'
                                       'Check that the file does not already '
                                       'exist and that you '
                                       'do not have file system permissions '
                                       'issues')
        layer = ogr_dataset.CreateLayer('contour')
        field_definition = ogr.FieldDefn('ID', ogr.OFTInteger)
        layer.CreateField(field_definition)
        field_definition = ogr.FieldDefn('MMI', ogr.OFTReal)
        layer.CreateField(field_definition)
        # So we can fix the x pos to the same x coord as centroid of the
        # feature so labels line up nicely vertically
        field_definition = ogr.FieldDefn('X', ogr.OFTReal)
        layer.CreateField(field_definition)
        # So we can fix the y pos to the min y coord of the whole contour so
        # labels line up nicely vertically
        field_definition = ogr.FieldDefn('Y', ogr.OFTReal)
        layer.CreateField(field_definition)
        # So that we can set the html hex colour based on its MMI class
        field_definition = ogr.FieldDefn('RGB', ogr.OFTString)
        layer.CreateField(field_definition)
        # So that we can set the label in it roman numeral form
        field_definition = ogr.FieldDefn('ROMAN', ogr.OFTString)
        layer.CreateField(field_definition)
        # So that we can set the label horizontal alignment
        field_definition = ogr.FieldDefn('ALIGN', ogr.OFTString)
        layer.CreateField(field_definition)
        # So that we can set the label vertical alignment
        field_definition = ogr.FieldDefn('VALIGN', ogr.OFTString)
        layer.CreateField(field_definition)
        # So that we can set feature length to filter out small features
        field_definition = ogr.FieldDefn('LEN', ogr.OFTReal)
        layer.CreateField(field_definition)

        tif_dataset = gdal.Open(tif_path, GA_ReadOnly)
        # see http://gdal.org/java/org/gdal/gdal/gdal.html for these options
        band = 1
        contour_interval = 0.5
        contour_base = 0
        fixed_level_list = []
        use_no_data_flag = 0
        no_data_value = -9999
        id_field = 0  # first field defined above
        elevation_field = 1  # second (MMI) field defined above
        try:
            gdal.ContourGenerate(tif_dataset.GetRasterBand(band),
                                 contour_interval,
                                 contour_base,
                                 fixed_level_list,
                                 use_no_data_flag,
                                 no_data_value,
                                 layer,
                                 id_field,
                                 elevation_field)
        except Exception, e:
            LOGGER.exception('Contour creation failed')
            raise ContourCreationError(str(e))
        finally:
            del tif_dataset
            ogr_dataset.Release()

        # Copy over the standard .prj file since ContourGenerate does not
        # create a projection definition
        qml_path = os.path.join(shakemapExtractDir(),
                                self.eventId,
                                'mmi-contours-%s.prj' % algorithm)
        source_qml = os.path.join(dataDir(), 'mmi-contours.prj')
        shutil.copyfile(source_qml, qml_path)

        # Lastly copy over the standard qml (QGIS Style file)
        qml_path = os.path.join(shakemapExtractDir(),
                                self.eventId,
                                'mmi-contours-%s.qml' % algorithm)
        source_qml = os.path.join(dataDir(), 'mmi-contours.qml')
        shutil.copyfile(source_qml, qml_path)

        # Now update the additional columns - X,Y, ROMAN and RGB
        try:
            self.set_contour_properties(output_file)
        except InvalidLayerError:
            raise

        return output_file

    def romanize(self, mmi_value):
        """Return the roman numeral for an mmi value.

        :param mmi_value: The MMI value that will be romanized
        :type mmi_value: float

        :return Roman numeral equivalent of the value
        :rtype: str
        """
        if mmi_value is None:
            LOGGER.debug('Romanize passed None')
            return ''

        LOGGER.debug('Romanising %f' % float(mmi_value))
        roman_list = ['0', 'I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII',
                      'IX', 'X', 'XI', 'XII']
        try:
            roman = roman_list[int(float(mmi_value))]
        except ValueError:
            LOGGER.exception('Error converting MMI value to roman')
            return None
        return roman

    def mmi_shaking(self, mmi_value):
        """Return the perceived shaking for an mmi value as translated string.
        :param mmi_value: float or int required.
        :return str: internationalised string representing perceived shaking
             level e.g. weak, severe etc.
        """
        my_shaking_dict = {
            1: self.tr('Not felt'),
            2: self.tr('Weak'),
            3: self.tr('Weak'),
            4: self.tr('Light'),
            5: self.tr('Moderate'),
            6: self.tr('Strong'),
            7: self.tr('Very strong'),
            8: self.tr('Severe'),
            9: self.tr('Violent'),
            10: self.tr('Extreme'),
        }
        return my_shaking_dict[mmi_value]

    def mmi_potential_damage(self, mmi_value):
        """Return the potential damage for an mmi value as translated string.
        :param mmi_value: float or int required.
        :return str: internationalised string representing potential damage
            level e.g. Light, Moderate etc.
        """
        my_damage_dict = {
            1: self.tr('None'),
            2: self.tr('None'),
            3: self.tr('None'),
            4: self.tr('None'),
            5: self.tr('Very light'),
            6: self.tr('Light'),
            7: self.tr('Moderate'),
            8: self.tr('Mod/Heavy'),
            9: self.tr('Heavy'),
            10: self.tr('Very heavy')
        }
        return my_damage_dict[mmi_value]

    def set_contour_properties(self, input_file):
        """
        Set the X, Y, RGB, ROMAN attributes of the contour layer.

        :param input_file: (Required) Name of the contour layer.
        :type input_file: str

        :return: None

        :raise InvalidLayerError if anything is amiss with the layer.
        """
        LOGGER.debug('set_contour_properties requested for %s.' % input_file)
        layer = QgsVectorLayer(input_file, 'mmi-contours', "ogr")
        if not layer.isValid():
            raise InvalidLayerError(input_file)

        layer.startEditing()
        # Now loop through the db adding selected features to mem layer
        request = QgsFeatureRequest()
        fields = layer.dataProvider().fields()

        for feature in layer.getFeatures(request):
            if not feature.isValid():
                LOGGER.debug('Skipping feature')
                continue
            # Work out x and y
            line = feature.geometry().asPolyline()
            y = line[0].y()

            x_max = line[0].x()
            x_min = x_max
            for point in line:
                if point.y() < y:
                    y = point.y()
                x = point.x()
                if x < x_min:
                    x_min = x
                if x > x_max:
                    x_max = x
            x = x_min + ((x_max - x_min) / 2)

            # Get length
            length = feature.geometry().length()

            mmi_value = float(feature['MMI'].toString())

            # We only want labels on the whole number contours
            if mmi_value != round(mmi_value):
                roman = ''
            else:
                roman = self.romanize(mmi_value)

            #LOGGER.debug('MMI: %s ----> %s' % (
            #    myAttributes[myMMIIndex].toString(), roman))

            # RGB from http://en.wikipedia.org/wiki/Mercalli_intensity_scale
            rgb = mmi_colour(mmi_value)

            # Now update the feature
            feature_id = feature.id()
            layer.changeAttributeValue(
                feature_id, fields.indexFromName('X'), QVariant(x))
            layer.changeAttributeValue(
                feature_id, fields.indexFromName('Y'), QVariant(y))
            layer.changeAttributeValue(
                feature_id, fields.indexFromName('RGB'), QVariant(rgb))
            layer.changeAttributeValue(
                feature_id, fields.indexFromName('ROMAN'), QVariant(roman))
            layer.changeAttributeValue(
                feature_id, fields.indexFromName('ALIGN'), QVariant('Center'))
            layer.changeAttributeValue(
                feature_id, fields.indexFromName('VALIGN'), QVariant('HALF'))
            layer.changeAttributeValue(
                feature_id, fields.indexFromName('LEN'), QVariant(length))

        layer.commitChanges()

    def bounds_to_rectangle(self):
        """Convert the event bounding box to a QgsRectangle.

        :return: QgsRectangle
        :raises: None
        """
        LOGGER.debug('bounds to rectangle called.')
        rectangle = QgsRectangle(self.x_minimum,
                                 self.y_maximum,
                                 self.x_maximum,
                                 self.y_minimum)
        return rectangle

    def cities_to_shapefile(self, force_flag=False):
        """Write a cities memory layer to a shapefile.

        :param force_flag: (Optional). Whether to force the overwrite
                of any existing data. Defaults to False.
        :type force_flag: bool

        :return str Path to the created shapefile
        :raise ShapefileCreationError

        .. note:: The file will be saved into the shakemap extract dir
           event id folder. Any existing shp by the same name will be
           overwritten if theForceFlag is False, otherwise it will
           be returned directly without creating a new file.
        """
        filename = 'mmi-cities'
        memory_layer = self.local_cities_memory_layer()
        return self.memory_layer_to_shapefile(file_name=filename,
                                              memory_layer=memory_layer,
                                              force_flag=force_flag)

    def city_search_boxes_to_shapefile(self, force_flag=False):
        """Write a cities memory layer to a shapefile.

        :param force_flag: bool (Optional). Whether to force the overwrite
                of any existing data. Defaults to False.
        .. note:: The file will be saved into the shakemap extract dir
           event id folder. Any existing shp by the same name will be
           overwritten if theForceFlag is False, otherwise it will
           be returned directly without creating a new file.

        :return str Path to the created shapefile
        :raise ShapefileCreationError
        """
        filename = 'city-search-boxes'
        memory_layer = self.city_search_box_memory_layer()
        return self.memory_layer_to_shapefile(file_name=filename,
                                              memory_layer=memory_layer,
                                              force_flag=force_flag)

    def memory_layer_to_shapefile(self,
                                  file_name,
                                  memory_layer,
                                  force_flag=False):
        """Write a memory layer to a shapefile.

        :param file_name: Filename excluding path and ext. e.g.
        'mmi-cities'
        :type file_name: str

        :param memory_layer: QGIS memory layer instance.

        :param force_flag: (Optional). Whether to force the overwrite
                of any existing data. Defaults to False.
        :type force_flag: bool

        .. note:: The file will be saved into the shakemap extract dir
           event id folder. If a qml matching theFileName.qml can be
           found it will automatically copied over to the output dir.
           Any existing shp by the same name will be overridden if
           theForceFlag is True, otherwise the existing file will be returned.

        :return str Path to the created shapefile
        :raise ShapefileCreationError
        """
        LOGGER.debug('memory_layer_to_shapefile requested.')

        LOGGER.debug(str(memory_layer.dataProvider().attributeIndexes()))
        if memory_layer.featureCount() < 1:
            raise ShapefileCreationError('Memory layer has no features')

        geo_crs = QgsCoordinateReferenceSystem()
        geo_crs.createFromId(4326, QgsCoordinateReferenceSystem.EpsgCrsId)

        output_file_base = os.path.join(shakemapExtractDir(),
                                        self.eventId,
                                        '%s.' % file_name)
        output_file = output_file_base + 'shp'
        if os.path.exists(output_file) and force_flag is not True:
            return output_file
        elif os.path.exists(output_file):
            try:
                os.remove(output_file_base + 'shp')
                os.remove(output_file_base + 'shx')
                os.remove(output_file_base + 'dbf')
                os.remove(output_file_base + 'prj')
            except OSError:
                LOGGER.exception(
                    'Old shape files not deleted'
                    ' - this may indicate a file permissions issue.')

        # Next two lines a workaround for a QGIS bug (lte 1.8)
        # preventing mem layer attributes being saved to shp.
        memory_layer.startEditing()
        memory_layer.commitChanges()

        LOGGER.debug('Writing mem layer to shp: %s' % output_file)
        # Explicitly giving all options, not really needed but nice for clarity
        error_message = QString()
        options = QStringList()
        layer_options = QStringList()
        selected_only_flag = False
        skip_attributes_flag = False
        # May differ from output_file
        actual_new_file_name = QString()
        result = QgsVectorFileWriter.writeAsVectorFormat(
            memory_layer,
            output_file,
            'utf-8',
            geo_crs,
            "ESRI Shapefile",
            selected_only_flag,
            error_message,
            options,
            layer_options,
            skip_attributes_flag,
            actual_new_file_name)

        if result == QgsVectorFileWriter.NoError:
            LOGGER.debug('Wrote mem layer to shp: %s' % output_file)
        else:
            raise ShapefileCreationError(
                'Failed with error: %s' % result)

        # Lastly copy over the standard qml (QGIS Style file) for the mmi.tif
        qml_path = os.path.join(shakemapExtractDir(),
                                self.eventId,
                                '%s.qml' % file_name)
        source_qml = os.path.join(dataDir(), '%s.qml' % file_name)
        shutil.copyfile(source_qml, qml_path)

        return output_file

    def local_city_features(self):
        """Create a list of features representing cities impacted.

        :return: List of QgsFeature instances, each representing a place/city.

        :raises: InvalidLayerError

        The following fields will be created for each city feature:

            QgsField('id', QVariant.Int),
            QgsField('name', QVariant.String),
            QgsField('population', QVariant.Int),
            QgsField('mmi', QVariant.Double),
            QgsField('dist_to', QVariant.Double),
            QgsField('dir_to', QVariant.Double),
            QgsField('dir_from', QVariant.Double),
            QgsField('roman', QVariant.String),
            QgsField('colour', QVariant.String),

        The 'name' and 'population' fields will be obtained from our geonames
        dataset.

        A raster lookup for each city will be done to set the mmi field
        in the city feature with the value on the raster. The raster should be
        one generated using :func:`mmiDatToRaster`. The raster will be created
        first if needed.

        The distance to and direction to/from fields will be set using QGIS
        geometry API.

        It is a requirement that there will always be at least one city
        on the map for context so we will iteratively do a city selection,
        starting with the extents of the MMI dataset and then zooming
        out by self.zoom_factor until we have some cities selected.

        After making a selection the extents used (taking into account the
        iterative scaling mentioned above) will be stored in the class
        attributes so that when producing a map it can be used to ensure
        the cities and the shake area are visible on the map. See
        :samp:`self.extent_with_cities` in :func:`__init__`.

        .. note:: We separate the logic of creating features from writing a
          layer so that we can write to any format we like whilst reusing the
          core logic.

        .. note:: The original dataset will be modified in place.
        """
        LOGGER.debug('localCityValues requested.')
        # Setup the raster layer for interpolated mmi lookups
        path = self.mmi_data_to_raster()
        file_info = QFileInfo(path)
        base_name = file_info.baseName()
        raster_layer = QgsRasterLayer(path, base_name)
        if not raster_layer.isValid():
            raise InvalidLayerError('Layer failed to load!\n%s' % path)

        # Setup the cities table, querying on event bbox
        # Path to sqlitedb containing geonames table
        db_path = os.path.join(dataDir(), 'indonesia.sqlite')
        uri = QgsDataSourceURI()
        uri.setDatabase(db_path)
        table = 'geonames'
        geometry_column = 'geom'
        schema = ''
        uri.setDataSource(schema, table, geometry_column)
        layer = QgsVectorLayer(uri.uri(), 'Towns', 'spatialite')
        if not layer.isValid():
            raise InvalidLayerError(db_path)
        rectangle = self.bounds_to_rectangle()

        # Do iterative selection using expanding selection area
        # Until we have got some cities selected

        attempts_limit = 5
        minimum_city_count = 1
        found_flag = False
        search_boxes = []
        request = None
        LOGGER.debug('Search polygons for cities:')
        for _ in range(attempts_limit):
            LOGGER.debug(rectangle.asWktPolygon())
            layer.removeSelection()
            request = QgsFeatureRequest().setFilterRect(rectangle)
            request.setFlags(QgsFeatureRequest.ExactIntersect)
            # This is klunky - must be a better way in the QGIS api!?
            # but layer.selectedFeatureCount() relates to gui
            # selection it seems...
            count = 0
            for _ in layer.getFeatures(request):
                count += 1
            # Store the box plus city count so we can visualise it later
            record = {'city_count': count, 'geometry': rectangle}
            LOGGER.debug('Found cities in search box: %s' % record)
            search_boxes.append(record)
            if count < minimum_city_count:
                rectangle.scale(self.zoomFactor)
            else:
                found_flag = True
                break

        self.search_boxes = search_boxes
        # TODO: Perhaps it might be neater to combine the bbox of cities and
        #       mmi to get a tighter AOI then do a small zoom out.
        self.extent_with_cities = rectangle
        if not found_flag:
            LOGGER.debug(
                'Could not find %s cities after expanding rect '
                '%s times.' % (minimum_city_count, attempts_limit))
        # Setup field indexes of our input and out datasets
        cities = []

        #myFields = QgsFields()
        #myFields.append(QgsField('id', QVariant.Int))
        #myFields.append(QgsField('name', QVariant.String))
        #myFields.append(QgsField('population', QVariant.Int))
        #myFields.append(QgsField('mmi', QVariant.Double))
        #myFields.append(QgsField('dist_to', QVariant.Double))
        #myFields.append(QgsField('dir_to', QVariant.Double))
        #myFields.append(QgsField('dir_from', QVariant.Double))
        #myFields.append(QgsField('roman', QVariant.String))
        #myFields.append(QgsField('colour', QVariant.String))

        # For measuring distance and direction from each city to epicenter
        epicenter = QgsPoint(self.longitude, self.latitude)

        # Now loop through the db adding selected features to mem layer
        for feature in layer.getFeatures(request):
            if not feature.isValid():
                LOGGER.debug('Skipping feature')
                continue
                #LOGGER.debug('Writing feature to mem layer')
            # calculate the distance and direction from this point
            # to and from the epicenter
            feature_id = str(feature.id())

            # Make sure the fcode contains PPL (populated place)
            code = str(feature['fcode'].toString())
            if 'PPL' not in code:
                continue

            # Make sure the place is populated
            population = feature['population'].toInt()[0]
            if population < 1:
                continue

            point = feature.geometry().asPoint()
            distance = point.sqrDist(epicenter)
            direction_to = point.azimuth(epicenter)
            direction_from = epicenter.azimuth(point)
            place_name = str(feature['asciiname'].toString())

            new_feature = QgsFeature()
            new_feature.setGeometry(feature.geometry())

            # Populate the mmi field by raster lookup
            # Get a {int, QVariant} back
            raster_values = raster_layer.dataProvider().identify(
                point, QgsRaster.IdentifyFormatValue).results()
            raster_values = raster_values.values()
            if not raster_values or len(raster_values) < 1:
                # position not found on raster
                continue
            value = raster_values[0]  # Band 1
            LOGGER.debug('MyValue: %s' % value)
            if 'no data' not in value.toString():
                mmi = value.toFloat()[0]
            else:
                mmi = 0

            LOGGER.debug('Looked up mmi of %s on raster for %s' %
                         (mmi, point.toString()))

            roman = self.romanize(mmi)
            if roman is None:
                continue

            # new_feature.setFields(myFields)
            # Column positions are determined by setFields above
            attributes = [
                feature_id,
                place_name,
                population,
                QVariant(mmi),
                QVariant(distance),
                QVariant(direction_to),
                QVariant(direction_from),
                QVariant(roman),
                QVariant(mmi_colour(mmi))]
            new_feature.setAttributes(attributes)
            cities.append(new_feature)
        return cities

    def local_cities_memory_layer(self):
        """Fetch a collection of the cities that are nearby.

        :return: A QGIS memory layer
        :rtype: QgsVectorLayer

        :raises: an exceptions will be propagated
        """
        LOGGER.debug('local_cities_memory_layer requested.')
        # Now store the selection in a temporary memory layer
        memory_layer = QgsVectorLayer('Point', 'affected_cities', 'memory')

        memory_provider = memory_layer.dataProvider()
        # add field defs
        memory_provider.addAttributes([
            QgsField('id', QVariant.Int),
            QgsField('name', QVariant.String),
            QgsField('population', QVariant.Int),
            QgsField('mmi', QVariant.Double),
            QgsField('dist_to', QVariant.Double),
            QgsField('dir_to', QVariant.Double),
            QgsField('dir_from', QVariant.Double),
            QgsField('roman', QVariant.String),
            QgsField('colour', QVariant.String)])
        cities = self.local_city_features()
        result = memory_provider.addFeatures(cities)
        if not result:
            LOGGER.exception('Unable to add features to cities memory layer')
            raise CityMemoryLayerCreationError(
                'Could not add any features to cities memory layer.')

        memory_layer.commitChanges()
        memory_layer.updateExtents()

        LOGGER.debug('Feature count of mem layer:  %s' %
                     memory_layer.featureCount())

        return memory_layer

    def city_search_box_memory_layer(self, force_flag=False):
        """Return the search boxes used to search for cities as a memory layer.

        This is mainly useful for diagnostic purposes.

        :param force_flag: (Optional). Whether to force the overwrite
                of any existing data. Defaults to False.
        :type force_flag: bool

        :return: A QGIS memory layer
        :rtype: QgsVectorLayer

        :raise: an exceptions will be propagated
        """
        LOGGER.debug('city_search_box_memory_layer requested.')
        # There is a dependency on local_cities_memory_layer so run it first
        if self.search_boxes is None or force_flag:
            self.local_cities_memory_layer()
        # Now store the selection in a temporary memory layer
        memory_layer = QgsVectorLayer('Polygon',
                                      'City Search Boxes',
                                      'memory')
        memory_provider = memory_layer.dataProvider()
        # add field defs
        field = QgsField('cities_found', QVariant.Int)
        memory_provider.addAttributes([field])
        features = []
        for search_box in self.search_boxes:
            new_feature = QgsFeature()
            rectangle = search_box['geometry']
            # noinspection PyArgumentList
            geometry = QgsGeometry.fromWkt(rectangle.asWktPolygon())
            new_feature.setGeometry(geometry)
            new_feature.setAttributes([search_box['city_count']])
            features.append(new_feature)

        result = memory_provider.addFeatures(features)
        if not result:
            LOGGER.exception('Unable to add features to city search boxes'
                             'memory layer')
            raise CityMemoryLayerCreationError(
                'Could not add any features to city search boxes memory layer')

        memory_layer.commitChanges()
        memory_layer.updateExtents()

        LOGGER.debug('Feature count of search box mem layer:  %s' %
                     memory_layer.featureCount())

        return memory_layer

    def sorted_impacted_cities(self, row_count=5):
        """Return a data structure with place, mmi, pop sorted by mmi then pop.

        :param row_count: optional limit to how many rows should be
                returned. Defaults to 5 if not specified.
        :type row_count: int

        :return: An list of dicts containing the sorted cities and their
                attributes. See below for example output.

                [{'dir_from': 16.94407844543457,
                 'dir_to': -163.05592346191406,
                 'roman': 'II',
                 'dist_to': 2.504295825958252,
                 'mmi': 1.909999966621399,
                 'name': 'Tondano',
                 'id': 57,
                 'population': 33317}]
        :rtype: list

        Straw man illustrating how sorting is done:

        m = [
             {'name': 'b', 'mmi': 10,  'pop':10},
             {'name': 'a', 'mmi': 100, 'pop': 20},
             {'name': 'c', 'mmi': 10, 'pop': 14}]

        sorted(m, key=lambda d: (-d['mmi'], -d['pop'], d['name']))
        Out[10]:
        [{'mmi': 100, 'name': 'a', 'pop': 20},
         {'mmi': 10, 'name': 'c', 'pop': 14},
         {'mmi': 10, 'name': 'b', 'pop': 10}]

        .. note:: self.most_affected_city will also be populated with
            the dictionary of details for the most affected city.

        .. note:: It is possible that there is no affected city! e.g. if
            all nearby cities fall outside of the shake raster.

        """
        layer = self.local_cities_memory_layer()
        fields = layer.dataProvider().fields()
        cities = []
        # pylint: disable=W0612
        count = 0
        # pylint: enable=W0612
        # Now loop through the db adding selected features to mem layer
        request = QgsFeatureRequest()

        for feature in layer.getFeatures(request):
            if not feature.isValid():
                LOGGER.debug('Skipping feature')
                continue
            count += 1
            # calculate the distance and direction from this point
            # to and from the epicenter
            feature_id = feature.id()
            # We should be able to do this:
            # place_name = str(feature['name'].toString())
            # But its not working so we do this:
            place_name = str(
                feature[fields.indexFromName('name')].toString())
            mmi = feature[fields.indexFromName('mmi')].toFloat()[0]
            population = (
                feature[fields.indexFromName('population')].toInt()[0])
            roman = str(
                feature[fields.indexFromName('roman')].toString())
            direction_to = (
                feature[fields.indexFromName('dir_to')].toFloat()[0])
            direction_from = (
                feature[fields.indexFromName('dir_from')].toFloat()[0])
            distance_to = (
                feature[fields.indexFromName('dist_to')].toFloat()[0])
            city = {'id': feature_id,
                    'name': place_name,
                    'mmi-int': int(mmi),
                    'mmi': mmi,
                    'population': population,
                    'roman': roman,
                    'dist_to': distance_to,
                    'dir_to': direction_to,
                    'dir_from': direction_from}
            cities.append(city)
        LOGGER.debug('%s features added to sorted impacted cities list.')
        #LOGGER.exception(cities)
        sorted_cities = sorted(cities,
                               key=lambda d: (
                               # we want to use whole no's for sort
                               - d['mmi-int'],
                               - d['population'],
                               d['name'],
                               d['mmi'],  # not decimals
                               d['roman'],
                               d['dist_to'],
                               d['dir_to'],
                               d['dir_from'],
                               d['id']))
        # TODO: Assumption that place names are unique is bad....
        if len(sorted_cities) > 0:
            self.most_affected_city = sorted_cities[0]
        else:
            self.most_affected_city = None
        # Slice off just the top row_count records now
        if len(sorted_cities) > 5:
            sorted_cities = sorted_cities[0: row_count]
        return sorted_cities

    def write_html_table(self, file_name, table):
        """Write a Table object to disk with a standard header and footer.

        This is a helper function that allows you to easily write a table
        to disk with a standard header and footer. The header contains
        some inlined css markup for our mmi charts which will be ignored
        if you are not using the css classes it defines.

        The bootstrap.css file will also be written to the same directory
        where the table is written.

        :param file_name: file name (without full path) .e.g foo.html
        :param table: A Table instance.
        :return: Full path to file that was created on disk.
        :rtype: str
        """
        path = os.path.join(shakemapExtractDir(),
                            self.eventId,
                            file_name)
        html_file = file(path, 'wt')
        header_file = os.path.join(dataDir(), 'header.html')
        footer_file = os.path.join(dataDir(), 'footer.html')
        header_file = file(header_file, 'rt')
        header = header_file.read()
        header_file.close()
        footer_file = file(footer_file, 'rt')
        footer = footer_file.read()
        footer_file.close()
        html_file.write(header)
        html_file.write(table.toNewlineFreeString())
        html_file.write(footer)
        html_file.close()
        # Also bootstrap gets copied to extract dir
        my_destination = os.path.join(shakemapExtractDir(),
                                      self.eventId,
                                      'bootstrap.css')
        my_source = os.path.join(dataDir(), 'bootstrap.css')
        shutil.copyfile(my_source, my_destination)

        return path

    def impacted_cities_table(self, row_count=5):
        """Return a table object of sorted impacted cities.
        :param row_count:optional maximum number of cities to show.
                Default is 5.

        The cities will be listed in the order computed by
        sorted_impacted_cities
        but will only list in the following format:

        +------+--------+-----------------+-----------+
        | Icon | Name   | People Affected | Intensity |
        +======+========+=================+===========+
        | img  | Padang |    2000         |    IV     +
        +------+--------+-----------------+-----------+

        .. note:: Population will be rounded pop / 1000

        The icon img will be an image with an icon showing the relevant colour.

        :returns:
            two tuple of:
                A Table object (see :func:`safe.impact_functions.tables.Table`)
                A file path to the html file saved to disk.

        :raise: Propagates any exceptions.
        """
        table_data = self.sorted_impacted_cities(row_count)
        table_body = []
        header = TableRow(['',
                           self.tr('Name'),
                           self.tr('Affected (x 1000)'),
                           self.tr('Intensity')],
                          header=True)
        for row_data in table_data:
            intensity = row_data['roman']
            name = row_data['name']
            population = int(round(row_data['population'] / 1000))
            colour = mmi_colour(row_data['mmi'])
            colour_box = ('<div style="width: 16px; height: 16px;'
                          'background-color: %s"></div>' % colour)
            row = TableRow([colour_box,
                            name,
                            population,
                            intensity])
            table_body.append(row)

        table = Table(table_body, header_row=header,
                      table_class='table table-striped table-condensed')
        # Also make an html file on disk
        path = self.write_html_table(file_name='affected-cities.html',
                                     table=table)

        return table, path

    def impact_table(self):
        """Create the html listing affected people per mmi interval.

        Expects that calculate impacts has run and set pop affected etc.
        already.

        self.: A dictionary with keys mmi levels and values affected count
                as per the example below. This is typically going to be passed
                from the :func:`calculate_impacts` function defined below.


        :return: Full absolute path to the saved html content.
        :rtype: str

        Example:
                {2: 0.47386375223673427,
                3: 0.024892573693488258,
                4: 0.0,
                5: 0.0,
                6: 0.0,
                7: 0.0,
                8: 0.0,
                9: 0.0}
        """
        header = [TableCell(self.tr('Intensity'), header=True)]
        affected_row = [
            TableCell(self.tr('People Affected (x 1000)'), header=True)]
        impact_row = [TableCell(self.tr('Perceived Shaking'), header=True)]
        for mmi in range(2, 10):
            header.append(
                TableCell(self.romanize(mmi),
                          cell_class='mmi-%s' % mmi,
                          header=True))
            if mmi in self.affected_counts:
                # noinspection PyTypeChecker
                affected_row.append(
                    '%i' % round(self.affected_counts[mmi] / 1000))
            else:
                # noinspection PyTypeChecker
                affected_row.append(0.00)

            impact_row.append(TableCell(self.mmi_shaking(mmi)))

        table_body = list()
        table_body.append(affected_row)
        table_body.append(impact_row)
        table = Table(table_body, header_row=header,
                      table_class='table table-striped table-condensed')
        path = self.write_html_table(file_name='impacts.html',
                                     table=table)
        return path

    def calculate_impacts(self,
                          population_raster_path=None,
                          force_flag=False,
                          algorithm='nearest'):
        """Use the SAFE ITB earthquake function to calculate impacts.

        :param population_raster_path: optional. see
                :func:`_getPopulationPath` for more details on how the path
                will be resolved if not explicitly given.
        :type population_raster_path: str

        :param force_flag: (Optional). Whether to force the
                regeneration of contour product. Defaults to False.
        :type force_flag: bool

        :param algorithm: (Optional) Which interpolation algorithm to
                use to create the underlying raster. see
                :func:`mmiToRasterData` for information about default
                behaviour
        :type algorithm: str

        :returns:
            str: the path to the computed impact file.
                The class members self.impact_file, self.fatality_counts,
                self.displaced_counts and self.affected_counts will be
                populated.
                self.*Counts are dicts containing fatality / displaced /
                affected counts for the shake events. Keys for the dict will be
                MMI classes (I-X) and values will be count type for that class.
            str: Path to the html report showing a table of affected people per
                mmi interval.
        """
        if (
                population_raster_path is None or (
                not os.path.isfile(population_raster_path) and not
                os.path.islink(population_raster_path))):

            exposure_path = self._getPopulationPath()
        else:
            exposure_path = population_raster_path

        hazard_path = self.mmi_data_to_raster(
            force_flag=force_flag,
            algorithm=algorithm)

        clipped_hazard, clipped_exposure = self.clip_layers(
            shake_raster_path=hazard_path,
            population_raster_path=exposure_path)

        clipped_hazard_layer = safe_read_layer(
            str(clipped_hazard.source()))
        clipped_exposure_layer = safe_read_layer(
            str(clipped_exposure.source()))
        layers = [clipped_hazard_layer, clipped_exposure_layer]

        function_id = 'I T B Fatality Function'
        function = safe_get_plugins(function_id)[0][function_id]

        result = safe_calculate_impact(layers, function)
        try:
            fatalities = result.keywords['fatalites_per_mmi']
            affected = result.keywords['exposed_per_mmi']
            displaced = result.keywords['displaced_per_mmi']
            total_fatalities = result.keywords['total_fatalities']
        except:
            LOGGER.exception(
                'Fatalities_per_mmi key not found in:\n%s' %
                result.keywords)
            raise
        # Copy the impact layer into our extract dir.
        tif_path = os.path.join(shakemapExtractDir(),
                                self.eventId,
                                'impact-%s.tif' % algorithm)
        shutil.copyfile(result.filename, tif_path)
        LOGGER.debug('Copied impact result to:\n%s\n' % tif_path)
        # Copy the impact keywords layer into our extract dir.
        keywords_path = os.path.join(
            shakemapExtractDir(),
            self.eventId,
            'impact-%s.keywords' % algorithm)
        keywords_source = os.path.splitext(result.filename)[0]
        keywords_source = '%s.keywords' % keywords_source
        shutil.copyfile(keywords_source, keywords_path)
        LOGGER.debug('Copied impact keywords to:\n%s\n' % keywords_path)

        self.impact_file = tif_path
        self.impact_keywords_file = keywords_path
        self.fatality_counts = fatalities
        self.fatality_total = total_fatalities
        self.displaced_counts = displaced
        self.affected_counts = affected
        LOGGER.info('***** Fatalities: %s ********' % self.fatality_counts)
        LOGGER.info('***** Displaced: %s ********' % self.displaced_counts)
        LOGGER.info('***** Affected: %s ********' % self.affected_counts)

        impact_table_path = self.impact_table()
        return self.impact_file, impact_table_path

    def clip_layers(self, shake_raster_path, population_raster_path):
        """Clip population (exposure) layer to dimensions of shake data.

        It is possible (though unlikely) that the shake may be clipped too.

        :param shake_raster_path: Path to the shake raster.

        :param population_raster_path: Path to the population raster.

        :return: Path to the clipped datasets (clipped shake, clipped pop).
        :rtype: tuple(str, str)

        :raise
            FileNotFoundError
        """

        # _ is a syntactical trick to ignore second returned value
        base_name, _ = os.path.splitext(shake_raster_path)
        hazard_layer = QgsRasterLayer(shake_raster_path, base_name)
        base_name, _ = os.path.splitext(population_raster_path)
        exposure_layer = QgsRasterLayer(population_raster_path, base_name)

        # Reproject all extents to EPSG:4326 if needed
        geo_crs = QgsCoordinateReferenceSystem()
        geo_crs.createFromId(4326, QgsCoordinateReferenceSystem.EpsgCrsId)

        # Get the Hazard extents as an array in EPSG:4326
        # Note that we will always clip to this extent regardless of
        # whether the exposure layer completely covers it. This differs
        # from safe_qgis which takes care to ensure that the two layers
        # have coincidental coverage before clipping. The
        # clipper function will take care to null padd any missing data.
        hazard_geo_extent = extent_to_geoarray(
            hazard_layer.extent(),
            hazard_layer.crs())

        # Next work out the ideal spatial resolution for rasters
        # in the analysis. If layers are not native WGS84, we estimate
        # this based on the geographic extents
        # rather than the layers native extents so that we can pass
        # the ideal WGS84 cell size and extents to the layer prep routines
        # and do all preprocessing in a single operation.
        # All this is done in the function getWGS84resolution
        extra_exposure_keywords = {}

        # Hazard layer is raster
        hazard_geo_cell_size = get_wgs84_resolution(hazard_layer)

        # In case of two raster layers establish common resolution
        exposure_geo_cell_size = get_wgs84_resolution(exposure_layer)

        if hazard_geo_cell_size < exposure_geo_cell_size:
            cell_size = hazard_geo_cell_size
        else:
            cell_size = exposure_geo_cell_size

        # Record native resolution to allow rescaling of exposure data
        if not numpy.allclose(cell_size, exposure_geo_cell_size):
            extra_exposure_keywords['resolution'] = exposure_geo_cell_size

        # The extents should already be correct but the cell size may need
        # resampling, so we pass the hazard layer to the clipper
        clipped_hazard = clip_layer(
            layer=hazard_layer,
            extent=hazard_geo_extent,
            cell_size=cell_size)

        clipped_exposure = clip_layer(
            layer=exposure_layer,
            extent=hazard_geo_extent,
            cell_size=cell_size,
            extra_keywords=extra_exposure_keywords)

        return clipped_hazard, clipped_exposure

    def _getPopulationPath(self):
        """Helper to determine population raster spath.

        The following priority will be used to determine the path:
            1) the class attribute self.populationRasterPath
                will be checked and if not None it will be used.
            2) the environment variable 'INASAFE_POPULATION_PATH' will be
               checked if set it will be used.
            4) A hard coded path of
               :file:`/fixtures/exposure/population.tif` will be appended
               to os.path.abspath(os.path.curdir)
            5) A hard coded path of
               :file:`/usr/local/share/inasafe/exposure/population.tif`
               will be used.

        Args:
            None
        Returns:
            str - path to a population raster file.
        Raises:
            FileNotFoundError

        TODO: Consider automatically fetching from
        http://web.clas.ufl.edu/users/atatem/pub/IDN.7z

        Also see http://web.clas.ufl.edu/users/atatem/pub/
        https://github.com/AIFDR/inasafe/issues/381
        """
        # When used via the scripts make_shakemap.sh
        myFixturePath = os.path.join(
            dataDir(), 'exposure', 'population.tif')

        myLocalPath = '/usr/local/share/inasafe/exposure/population.tif'
        if self.populationRasterPath is not None:
            return self.populationRasterPath
        elif 'INASAFE_POPULATION_PATH' in os.environ:
            return os.environ['INASAFE_POPULATION_PATH']
        elif os.path.exists(myFixturePath):
            return myFixturePath
        elif os.path.exists(myLocalPath):
            return myLocalPath
        else:
            raise FileNotFoundError('Population file could not be found')

    def renderMap(self, theForceFlag=False):
        """This is the 'do it all' method to render a pdf.

        :param theForceFlag: bool - (Optional). Whether to force the
                regeneration of map product. Defaults to False.
        :return str - path to rendered pdf.
        :raise Propagates any exceptions.
        """
        myPdfPath = os.path.join(shakemapExtractDir(),
                                 self.eventId,
                                 '%s-%s.pdf' % (self.eventId, self.locale))
        myImagePath = os.path.join(shakemapExtractDir(),
                                   self.eventId,
                                   '%s-%s.png' % (self.eventId, self.locale))
        myThumbnailImagePath = os.path.join(shakemapExtractDir(),
                                            self.eventId,
                                            '%s-thumb-%s.png' % (
                                            self.eventId, self.locale))
        pickle_path = os.path.join(
            shakemapExtractDir(),
            self.eventId,
            '%s-metadata-%s.pickle' % (self.eventId, self.locale))

        if not theForceFlag:
            # Check if the images already exist and if so
            # short circuit.
            myShortCircuitFlag = True
            if not os.path.exists(myPdfPath):
                myShortCircuitFlag = False
            if not os.path.exists(myImagePath):
                myShortCircuitFlag = False
            if not os.path.exists(myThumbnailImagePath):
                myShortCircuitFlag = False
            if myShortCircuitFlag:
                LOGGER.info('%s (already exists)' % myPdfPath)
                LOGGER.info('%s (already exists)' % myImagePath)
                LOGGER.info('%s (already exists)' % myThumbnailImagePath)
                return myPdfPath

        # Make sure the map layers have all been removed before we
        # start otherwise in batch mode we will get overdraws.
        # noinspection PyArgumentList
        QgsMapLayerRegistry.instance().removeAllMapLayers()

        myMmiShapeFile = self.mmi_data_to_shapefile(force_flag=theForceFlag)
        logging.info('Created: %s', myMmiShapeFile)
        myCitiesHtmlPath = None
        myCitiesShapeFile = None

        # 'average', 'invdist', 'nearest' - currently only nearest works
        myAlgorithm = 'nearest'
        try:
            myContoursShapeFile = self.mmi_data_to_contours(
                force_flag=theForceFlag,
                algorithm=myAlgorithm)
        except:
            raise
        logging.info('Created: %s', myContoursShapeFile)
        try:
            myCitiesShapeFile = self.cities_to_shapefile(
                force_flag=theForceFlag)
            logging.info('Created: %s', myCitiesShapeFile)
            mySearchBoxFile = self.city_search_boxes_to_shapefile(
                force_flag=theForceFlag)
            logging.info('Created: %s', mySearchBoxFile)
            _, myCitiesHtmlPath = self.impacted_cities_table()
            logging.info('Created: %s', myCitiesHtmlPath)
        except:  # pylint: disable=W0702
            logging.exception('No nearby cities found!')

        _, myImpactsHtmlPath = self.calculate_impacts()
        logging.info('Created: %s', myImpactsHtmlPath)

        # Load our project
        if 'INSAFE_REALTIME_PROJECT' in os.environ:
            myProjectPath = os.environ['INSAFE_REALTIME_PROJECT']
        else:
            myProjectPath = os.path.join(dataDir(), 'realtime.qgs')
        # noinspection PyArgumentList
        QgsProject.instance().setFileName(myProjectPath)
        # noinspection PyArgumentList
        QgsProject.instance().read()

        if 'INSAFE_REALTIME_TEMPLATE' in os.environ:
            myTemplatePath = os.environ['INSAFE_REALTIME_TEMPLATE']
        else:
            myTemplatePath = os.path.join(dataDir(), 'realtime-template.qpt')

        myTemplateFile = file(myTemplatePath, 'rt')
        myTemplateContent = myTemplateFile.read()
        myTemplateFile.close()

        myDocument = QDomDocument()
        myDocument.setContent(myTemplateContent)

        # Set up the map renderer that will be assigned to the composition
        myMapRenderer = QgsMapRenderer()
        # Set the labelling engine for the canvas
        myLabellingEngine = QgsPalLabeling()
        myMapRenderer.setLabelingEngine(myLabellingEngine)

        # Enable on the fly CRS transformations
        myMapRenderer.setProjectionsEnabled(False)
        # Now set up the composition
        myComposition = QgsComposition(myMapRenderer)

        # You can use this to replace any string like this [key]
        # in the template with a new value. e.g. to replace
        # [date] pass a map like this {'date': '1 Jan 2012'}
        myLocationInfo = self.eventInfo()
        LOGGER.debug(myLocationInfo)
        mySubstitutionMap = {'location-info': myLocationInfo,
                             'version': self.version()}
        mySubstitutionMap.update(self.eventDict())
        LOGGER.debug(mySubstitutionMap)

        pickle_file = file(pickle_path, 'w')
        pickle.dump(mySubstitutionMap, pickle_file)
        pickle_file.close()

        myResult = myComposition.loadFromTemplate(myDocument,
                                                  mySubstitutionMap)
        if not myResult:
            LOGGER.exception('Error loading template %s with keywords\n %s',
                             myTemplatePath, mySubstitutionMap)
            raise MapComposerError

        # Get the main map canvas on the composition and set
        # its extents to the event.
        myMap = myComposition.getComposerMapById(0)
        if myMap is not None:
            myMap.setNewExtent(self.extent_with_cities)
            myMap.renderModeUpdateCachedImage()
        else:
            LOGGER.exception('Map 0 could not be found in template %s',
                             myTemplatePath)
            raise MapComposerError

        # Set the impacts report up
        myImpactsItem = myComposition.getComposerItemById(
            'impacts-table')
        if myImpactsItem is None:
            myMessage = 'impacts-table composer item could not be found'
            LOGGER.exception(myMessage)
            raise MapComposerError(myMessage)
        myImpactsHtml = myComposition.getComposerHtmlByItem(
            myImpactsItem)
        if myImpactsHtml is None:
            myMessage = 'Impacts QgsComposerHtml could not be found'
            LOGGER.exception(myMessage)
            raise MapComposerError(myMessage)
        myImpactsHtml.setUrl(QUrl(myImpactsHtmlPath))

        # Set the affected cities report up
        myCitiesItem = myComposition.getComposerItemById('affected-cities')
        if myCitiesItem is None:
            myMessage = 'affected-cities composer item could not be found'
            LOGGER.exception(myMessage)
            raise MapComposerError(myMessage)
        myCitiesHtml = myComposition.getComposerHtmlByItem(myCitiesItem)
        if myCitiesHtml is None:
            myMessage = 'Cities QgsComposerHtml could not be found'
            LOGGER.exception(myMessage)
            raise MapComposerError(myMessage)

        if myCitiesHtmlPath is not None:
            myCitiesHtml.setUrl(QUrl(myCitiesHtmlPath))
        else:
            # We used to raise an error here but it is actually feasible that
            # no nearby cities with a valid mmi value are found - e.g.
            # if the event is way out in the ocean.
            LOGGER.info('No nearby cities found.')

        # Load the contours and cities shapefile into the map
        myContoursLayer = QgsVectorLayer(
            myContoursShapeFile,
            'mmi-contours', "ogr")
        # noinspection PyArgumentList
        QgsMapLayerRegistry.instance().addMapLayers([myContoursLayer])

        myCitiesLayer = None
        if myCitiesShapeFile is not None:
            myCitiesLayer = QgsVectorLayer(
                myCitiesShapeFile,
                'mmi-cities', "ogr")
            if myCitiesLayer.isValid():
                # noinspection PyArgumentList
                QgsMapLayerRegistry.instance().addMapLayers([myCitiesLayer])

        # Now add our layers to the renderer so they appear in the print out
        myLayers = reversed(CANVAS.layers())
        myLayerList = []
        for myLayer in myLayers:
            myLayerList.append(myLayer.id())

        myLayerList.append(myContoursLayer.id())
        if myCitiesLayer is not None and myCitiesLayer.isValid():
            myLayerList.append(myCitiesLayer.id())

        myMapRenderer.setLayerSet(myLayerList)
        LOGGER.info(str(myLayerList))

        # Save a pdf.
        myComposition.exportAsPDF(myPdfPath)
        LOGGER.info('Generated PDF: %s' % myPdfPath)
        # Save a png
        myPageNumber = 0
        myImage = myComposition.printPageAsRaster(myPageNumber)
        myImage.save(myImagePath)
        LOGGER.info('Generated Image: %s' % myImagePath)
        # Save a thumbnail
        mySize = QSize(200, 200)
        myThumbnailImage = myImage.scaled(
            mySize, Qt.KeepAspectRatioByExpanding)
        myThumbnailImage.save(myThumbnailImagePath)
        LOGGER.info('Generated Thumbnail: %s' % myThumbnailImagePath)

        # Save a QGIS Composer template that you can open in QGIS
        myTemplateDocument = QDomDocument()
        myElement = myTemplateDocument.createElement('Composer')
        myComposition.writeXML(
            myElement, myTemplateDocument)
        myTemplateDocument.appendChild(myElement)
        myTemplatePath = os.path.join(
            shakemapExtractDir(),
            self.eventId,
            'composer-template.qpt')
        myFile = file(myTemplatePath, 'wt')
        myFile.write(myTemplateDocument.toByteArray())
        myFile.close()

        # Save a QGIS project that you can open in QGIS
        # noinspection PyArgumentList
        myProject = QgsProject.instance()
        myProjectPath = os.path.join(
            shakemapExtractDir(),
            self.eventId,
            'project.qgs')
        myProject.write(QFileInfo(myProjectPath))

    def bearingToCardinal(self, theBearing):
        """Given a bearing in degrees return it as compass units e.g. SSE.

        :param theBearing: theBearing float (required)
        :return str Compass bearing derived from theBearing or None if
            theBearing is None or can not be resolved to a float.

        .. note:: This method is heavily based on http://hoegners.de/Maxi/geo/
           which is licensed under the GPL V3.
        """
        myDirectionList = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE',
                           'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW',
                           'NW', 'NNW']
        try:
            myBearing = float(theBearing)
        except ValueError:
            LOGGER.exception('Error casting bearing to a float')
            return None

        myDirectionsCount = len(myDirectionList)
        myDirectionsInterval = 360. / myDirectionsCount
        myIndex = int(round(myBearing / myDirectionsInterval))
        myIndex %= myDirectionsCount
        return myDirectionList[myIndex]

    def eventInfo(self):
        """Get a short paragraph describing the event.

        Args:
            None

        Returns:
            str: A string describing the event e.g.
                'M 5.0 26-7-2012 2:15:35 Latitude: 0°12'36.00"S
                 Longitude: 124°27'0.00"E Depth: 11.0km
                 Located 2.50km SSW of Tondano'
        Raises:
            None
        """
        myDict = self.eventDict()
        myString = ('M %(mmi)s %(date)s %(time)s '
                    '%(latitude-name)s: %(latitude-value)s '
                    '%(longitude-name)s: %(longitude-value)s '
                    '%(depth-name)s: %(depth-value)s%(depth-unit)s '
                    '%(located-label)s %(distance)s%(distance-unit)s '
                    '%(bearing-compass)s '
                    '%(direction-relation)s %(place-name)s') % myDict
        return myString

    def eventDict(self):
        """Get a dict of key value pairs that describe the event.

        Args:

        Returns:
            dict: key-value pairs describing the event.

        Raises:
            propagates any exceptions

        """
        myMapName = self.tr('Estimated Earthquake Impact')
        myExposureTableName = self.tr(
            'Estimated number of people affected by each MMI level')
        myFatalitiesName = self.tr('Estimated fatalities')
        myFatalitiesCount = self.fatality_total

        # put the estimate into neat ranges 0-100, 100-1000, 1000-10000. etc
        myLowerLimit = 0
        myUpperLimit = 100
        while myFatalitiesCount > myUpperLimit:
            myLowerLimit = myUpperLimit
            myUpperLimit = math.pow(myUpperLimit, 2)
        myFatalitiesRange = '%i - %i' % (myLowerLimit, myUpperLimit)

        myCityTableName = self.tr('Places Affected')
        myLegendName = self.tr('Population density')
        myLimitations = self.tr(
            'This impact estimation is automatically generated and only takes'
            ' into account the population and cities affected by different '
            'levels of ground shaking. The estimate is based on ground '
            'shaking data from BMKG, population density data from asiapop'
            '.org, place information from geonames.org and software developed'
            ' by BNPB. Limitations in the estimates of ground shaking, '
            'population  data and place names datasets may result in '
            'significant misrepresentation of the on-the-ground situation in '
            'the figures shown here. Consequently decisions should not be '
            'made solely on the information presented here and should always '
            'be verified by ground truthing and other reliable information '
            'sources. The fatality calculation assumes that '
            'no fatalities occur for shake levels below MMI 4. Fatality '
            'counts of less than 50 are disregarded.')
        myCredits = self.tr(
            'Supported by the Australia-Indonesia Facility for Disaster '
            'Reduction, Geoscience Australia and the World Bank-GFDRR.')
        #Format the lat lon from decimal degrees to dms
        myPoint = QgsPoint(self.longitude, self.latitude)
        myCoordinates = myPoint.toDegreesMinutesSeconds(2)
        myTokens = myCoordinates.split(',')
        myLongitude = myTokens[0]
        myLatitude = myTokens[1]
        myKmText = self.tr('km')
        myDirectionalityText = self.tr('of')
        myBearingText = self.tr('bearing')
        LOGGER.debug(myLongitude)
        LOGGER.debug(myLatitude)
        if self.most_affected_city is None:
            # Check why we have this line - perhaps setting class state?
            self.sorted_impacted_cities()
            myDirection = 0
            myDistance = 0
            myKeyCityName = self.tr('n/a')
            myBearing = self.tr('n/a')
        else:
            myDirection = self.most_affected_city['dir_to']
            myDistance = self.most_affected_city['dist_to']
            myKeyCityName = self.most_affected_city['name']
            myBearing = self.bearingToCardinal(myDirection)

        myElapsedTimeText = self.tr('Elapsed time since event')
        myElapsedTime = self.elapsedTime()[1]
        myDegreeSymbol = '\xb0'
        myDict = {
            'map-name': myMapName,
            'exposure-table-name': myExposureTableName,
            'city-table-name': myCityTableName,
            'legend-name': myLegendName,
            'limitations': myLimitations,
            'credits': myCredits,
            'fatalities-name': myFatalitiesName,
            'fatalities-range': myFatalitiesRange,
            'fatalities-count': '%s' % myFatalitiesCount,
            'mmi': '%s' % self.magnitude,
            'date': '%s-%s-%s' % (
                self.day, self.month, self.year),
            'time': '%s:%s:%s' % (
                self.hour, self.minute, self.second),
            'formatted-date-time': self.elapsedTime()[0],
            'latitude-name': self.tr('Latitude'),
            'latitude-value': '%s' % myLatitude,
            'longitude-name': self.tr('Longitude'),
            'longitude-value': '%s' % myLongitude,
            'depth-name': self.tr('Depth'),
            'depth-value': '%s' % self.depth,
            'depth-unit': myKmText,
            'located-label': self.tr('Located'),
            'distance': '%.2f' % myDistance,
            'distance-unit': myKmText,
            'direction-relation': myDirectionalityText,
            'bearing-degrees': '%.2f%s' % (myDirection, myDegreeSymbol),
            'bearing-compass': '%s' % myBearing,
            'bearing-text': myBearingText,
            'place-name': myKeyCityName,
            'elapsed-time-name': myElapsedTimeText,
            'elapsed-time': myElapsedTime
        }
        return myDict

    def elapsedTime(self):
        """Calculate how much time has elapsed since the event.

        Args:
            None

        Returns:
            str - local formatted date

        Raises:
            None

        .. note:: Code based on Ole's original impact_map work.
        """
        # Work out interval since earthquake (assume both are GMT)
        year = self.year
        month = self.month
        day = self.day
        hour = self.hour
        minute = self.minute
        second = self.second

        eq_date = datetime(year, month, day, hour, minute, second)

        # Hack - remove when ticket:10 has been resolved
        tz = pytz.timezone('Asia/Jakarta')  # Or 'Etc/GMT+7'
        now = datetime.utcnow()
        now_jakarta = now.replace(tzinfo=pytz.utc).astimezone(tz)
        eq_jakarta = eq_date.replace(tzinfo=tz).astimezone(tz)
        time_delta = now_jakarta - eq_jakarta

        # Work out string to report time elapsed after quake
        if time_delta.days == 0:
            # This is within the first day after the quake
            hours = int(time_delta.seconds / 3600)
            minutes = int((time_delta.seconds % 3600) / 60)

            if hours == 0:
                lapse_string = '%i %s' % (minutes, self.tr('minute(s)'))
            else:
                lapse_string = '%i %s %i %s' % (hours,
                                                self.tr('hour(s)'),
                                                minutes,
                                                self.tr('minute(s)'))
        else:
            # This at least one day after the quake

            weeks = int(time_delta.days / 7)
            days = int(time_delta.days % 7)

            if weeks == 0:
                lapse_string = '%i %s' % (days, self.tr('days'))
            else:
                lapse_string = '%i %s %i %s' % (weeks,
                                                self.tr('weeks'),
                                                days,
                                                self.tr('days'))

        # Convert date to GMT+7
        # FIXME (Ole) Hack - Remove this as the shakemap data always
        # reports the time in GMT+7 but the timezone as GMT.
        # This is the topic of ticket:10
        #tz = pytz.timezone('Asia/Jakarta')  # Or 'Etc/GMT+7'
        #eq_date_jakarta = eq_date.replace(tzinfo=pytz.utc).astimezone(tz)
        eq_date_jakarta = eq_date

        # The character %b will use the local word for month
        # However, setting the locale explicitly to test, does not work.
        #locale.setlocale(locale.LC_TIME, 'id_ID')

        date_str = eq_date_jakarta.strftime('%d-%b-%y %H:%M:%S %Z')
        return date_str, lapse_string

    def version(self):
        """Return a string showing the version of Inasafe.

        Args: None

        Returns: str
        """
        return self.tr('Version: %s' % get_version())

    def getCityById(self, theId):
        """A helper to get the info of an affected city given it's id.

        :param theId: int mandatory, the id number of the city to retrieve.
        :return dict: various properties for the given city including distance
                from the epicenter and direction to and from the epicenter.
        """

    def __str__(self):
        """The unicode representation for an event object's state.

        Args: None

        Returns: str A string describing the ShakeEvent instance

        Raises: None
        """
        if self.extent_with_cities is not None:
            # noinspection PyUnresolvedReferences
            myExtentWithCities = self.extent_with_cities.asWktPolygon()
        else:
            myExtentWithCities = 'Not set'

        if self.mmi_data:
            mmiData = 'Populated'
        else:
            mmiData = 'Not populated'

        myDict = {'latitude': self.latitude,
                  'longitude': self.longitude,
                  'eventId': self.eventId,
                  'magnitude': self.magnitude,
                  'depth': self.depth,
                  'description': self.description,
                  'location': self.location,
                  'day': self.day,
                  'month': self.month,
                  'year': self.year,
                  'time': self.time,
                  'time_zone': self.timezone,
                  'x_minimum': self.x_minimum,
                  'x_maximum': self.x_maximum,
                  'y_minimum': self.y_minimum,
                  'y_maximum': self.y_maximum,
                  'rows': self.rows,
                  'columns': self.columns,
                  'mmi_data': mmiData,
                  'populationRasterPath': self.populationRasterPath,
                  'impact_file': self.impact_file,
                  'impact_keywords_file': self.impact_keywords_file,
                  'fatality_counts': self.fatality_counts,
                  'displaced_counts': self.displaced_counts,
                  'affected_counts': self.affected_counts,
                  'extent_with_cities': myExtentWithCities,
                  'zoom_factor': self.zoomFactor,
                  'search_boxes': self.search_boxes}

        myString = (
            'latitude: %(latitude)s\n'
            'longitude: %(longitude)s\n'
            'eventId: %(eventId)s\n'
            'magnitude: %(magnitude)s\n'
            'depth: %(depth)s\n'
            'description: %(description)s\n'
            'location: %(location)s\n'
            'day: %(day)s\n'
            'month: %(month)s\n'
            'year: %(year)s\n'
            'time: %(time)s\n'
            'time_zone: %(time_zone)s\n'
            'x_minimum: %(x_minimum)s\n'
            'x_maximum: %(x_maximum)s\n'
            'y_minimum: %(y_minimum)s\n'
            'y_maximum: %(y_maximum)s\n'
            'rows: %(rows)s\n'
            'columns: %(columns)s\n'
            'mmi_data: %(mmi_data)s\n'
            'populationRasterPath: %(populationRasterPath)s\n'
            'impact_file: %(impact_file)s\n'
            'impact_keywords_file: %(impact_keywords_file)s\n'
            'fatality_counts: %(fatality_counts)s\n'
            'displaced_counts: %(displaced_counts)s\n'
            'affected_counts: %(affected_counts)s\n'
            'extent_with_cities: %(extent_with_cities)s\n'
            'zoom_factor: %(zoom_factor)s\n'
            'search_boxes: %(search_boxes)s\n'
            % myDict)
        return myString

    def setupI18n(self):
        """Setup internationalisation for the reports.

        Args:
           None
        Returns:
           None.
        Raises:
           TranslationLoadException
        """
        myLocaleName = self.locale
        # Also set the system locale to the user overridden local
        # so that the inasafe library functions gettext will work
        # .. see:: :py:func:`common.utilities`
        os.environ['LANG'] = str(myLocaleName)

        myRoot = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        myTranslationPath = os.path.join(
            myRoot, 'safe_qgis', 'i18n',
            'inasafe_' + str(myLocaleName) + '.qm')
        if os.path.exists(myTranslationPath):
            self.translator = QTranslator()
            myResult = self.translator.load(myTranslationPath)
            LOGGER.debug('Switched locale to %s' % myTranslationPath)
            if not myResult:
                myMessage = 'Failed to load translation for %s' % myLocaleName
                LOGGER.exception(myMessage)
                raise TranslationLoadError(myMessage)
            # noinspection PyTypeChecker
            QCoreApplication.installTranslator(self.translator)
        else:
            if myLocaleName != 'en':
                myMessage = 'No translation exists for %s' % myLocaleName
                LOGGER.exception(myMessage)
