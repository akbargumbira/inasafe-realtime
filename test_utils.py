"""
InaSAFE Disaster risk assessment tool developed by AusAid and World Bank
- **Functionality related to shake data files.**

Contact : ole.moller.nielsen@gmail.com

.. note:: This program is free software; you can redistribute it and/or modify
     it under the terms of the GNU General Public License as published by
     the Free Software Foundation; either version 2 of the License, or
     (at your option) any later version.

"""

__author__ = 'tim@linfiniti.com'
__version__ = '0.5.0'
__date__ = '30/07/2012'
__copyright__ = ('Copyright 2012, Australia Indonesia Facility for '
                 'Disaster Reduction')

import unittest
from realtime.utils import (baseDataDir,
                            gisDataDir,
                            shakemapDataDir,
                            reportDataDir)


class Test(unittest.TestCase):

    def test_baseDataDir(self):
        """Test we can get the realtime data dir"""
        myDir = baseDataDir()
        myExpectedDir = '/tmp/inasafe/realtime'
        self.assertEqual(myDir, myExpectedDir)

    def test_gisDataDir(self):
        """Test web can get the gis data dir"""
        myDir = gisDataDir()
        myExpectedDir = '/tmp/inasafe/realtime/gis'
        self.assertEqual(myDir, myExpectedDir)

    def test_shakemapDataDir(self):
        """Test we can get the shakemap data dir"""
        myDir = shakemapDataDir()
        myExpectedDir = '/tmp/inasafe/realtime/shakemaps'
        self.assertEqual(myDir, myExpectedDir)

    def test_reportDataDir(self):
        """Test we can get the report data dir"""
        myDir = reportDataDir()
        myExpectedDir = '/tmp/inasafe/realtime/reports'
        self.assertEqual(myDir, myExpectedDir)

if __name__ == '__main__':
    unittest.main()
