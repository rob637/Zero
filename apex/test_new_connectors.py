"""
Tests for New Connectors (Phase 4)

Tests for:
- GoogleSheetsConnector
- GoogleSlidesConnector
- GooglePhotosConnector
- OneNoteConnector
- TwitterConnector
- SmartThingsConnector

These tests verify:
- Connector instantiation
- Data class structure
- Method signatures
- Registration in registry
"""

import asyncio
import unittest
from datetime import datetime, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))


# ============================================================================
# Google Sheets Tests
# ============================================================================

class TestGoogleSheetsConnector(unittest.TestCase):
    """Tests for SheetsConnector."""
    
    def test_import(self):
        """Test connector can be imported."""
        from connectors.google_sheets import SheetsConnector, Spreadsheet, Sheet
        self.assertIsNotNone(SheetsConnector)
    
    def test_spreadsheet_dataclass(self):
        """Test Spreadsheet data class."""
        from connectors.google_sheets import Spreadsheet
        
        spreadsheet = Spreadsheet(
            id="abc123",
            title="Test Sheet",
            url="https://docs.google.com/spreadsheets/d/abc123",
        )
        
        self.assertEqual(spreadsheet.id, "abc123")
        self.assertEqual(spreadsheet.title, "Test Sheet")
        
        # Test to_dict
        d = spreadsheet.to_dict()
        self.assertIn("id", d)
        self.assertIn("title", d)
        self.assertIn("url", d)
    
    def test_sheet_dataclass(self):
        """Test Sheet data class."""
        from connectors.google_sheets import Sheet
        
        sheet = Sheet(
            id=0,
            title="Sheet1",
            index=0,
            row_count=1000,
            column_count=26,
        )
        
        self.assertEqual(sheet.id, 0)
        self.assertEqual(sheet.title, "Sheet1")
        self.assertEqual(sheet.row_count, 1000)
        
        d = sheet.to_dict()
        self.assertIn("id", d)
        self.assertIn("title", d)
    
    def test_connector_instantiation(self):
        """Test connector can be instantiated."""
        from connectors.google_sheets import SheetsConnector
        
        connector = SheetsConnector()
        self.assertFalse(connector._service is not None)
    
    def test_connector_has_required_methods(self):
        """Test connector has required CRUD methods."""
        from connectors.google_sheets import SheetsConnector
        
        connector = SheetsConnector()
        
        # Check required methods exist
        self.assertTrue(hasattr(connector, 'connect'))
        self.assertTrue(hasattr(connector, 'get_spreadsheet'))
        self.assertTrue(hasattr(connector, 'create_spreadsheet'))
        self.assertTrue(hasattr(connector, 'read_range'))
        self.assertTrue(hasattr(connector, 'write_range'))


# ============================================================================
# Google Slides Tests
# ============================================================================

class TestGoogleSlidesConnector(unittest.TestCase):
    """Tests for SlidesConnector."""
    
    def test_import(self):
        """Test connector can be imported."""
        from connectors.google_slides import SlidesConnector, Presentation, Slide
        self.assertIsNotNone(SlidesConnector)
    
    def test_presentation_dataclass(self):
        """Test Presentation data class."""
        from connectors.google_slides import Presentation
        
        presentation = Presentation(
            id="pres123",
            title="Test Presentation",
            url="https://docs.google.com/presentation/d/pres123",
        )
        
        self.assertEqual(presentation.id, "pres123")
        self.assertEqual(presentation.title, "Test Presentation")
        
        d = presentation.to_dict()
        self.assertIn("id", d)
        self.assertIn("title", d)
    
    def test_slide_dataclass(self):
        """Test Slide data class."""
        from connectors.google_slides import Slide
        
        slide = Slide(
            id="slide1",
            index=0,
            layout="TITLE",
        )
        
        self.assertEqual(slide.id, "slide1")
        self.assertEqual(slide.index, 0)
        
        d = slide.to_dict()
        self.assertIn("id", d)
        self.assertIn("index", d)
    
    def test_connector_instantiation(self):
        """Test connector can be instantiated."""
        from connectors.google_slides import SlidesConnector
        
        connector = SlidesConnector()
        self.assertFalse(connector._service is not None)
    
    def test_connector_has_required_methods(self):
        """Test connector has required methods."""
        from connectors.google_slides import SlidesConnector
        
        connector = SlidesConnector()
        
        self.assertTrue(hasattr(connector, 'connect'))
        self.assertTrue(hasattr(connector, 'get_presentation'))
        self.assertTrue(hasattr(connector, 'create_presentation'))
        self.assertTrue(hasattr(connector, 'add_slide'))


# ============================================================================
# Google Photos Tests
# ============================================================================

class TestGooglePhotosConnector(unittest.TestCase):
    """Tests for PhotosConnector."""
    
    def test_import(self):
        """Test connector can be imported."""
        from connectors.google_photos import PhotosConnector, Album, MediaItem
        self.assertIsNotNone(PhotosConnector)
    
    def test_album_dataclass(self):
        """Test Album data class."""
        from connectors.google_photos import Album
        
        album = Album(
            id="album123",
            title="Vacation 2024",
            product_url="https://photos.google.com/album/album123",
            media_items_count=50,
        )
        
        self.assertEqual(album.id, "album123")
        self.assertEqual(album.title, "Vacation 2024")
        self.assertEqual(album.media_items_count, 50)
        
        d = album.to_dict()
        self.assertIn("id", d)
        self.assertIn("title", d)
    
    def test_media_item_dataclass(self):
        """Test MediaItem data class."""
        from connectors.google_photos import MediaItem
        
        item = MediaItem(
            id="photo123",
            filename="vacation.jpg",
            mime_type="image/jpeg",
            product_url="https://photos.google.com/photo/photo123",
            base_url="https://lh3.googleusercontent.com/photo123",
            creation_time=datetime.now(),
            width=1920,
            height=1080,
        )
        
        self.assertEqual(item.id, "photo123")
        self.assertEqual(item.filename, "vacation.jpg")
        self.assertEqual(item.width, 1920)
        self.assertTrue(item.is_photo)
        self.assertFalse(item.is_video)
        
        d = item.to_dict()
        self.assertIn("id", d)
        self.assertIn("filename", d)
    
    def test_connector_instantiation(self):
        """Test connector can be instantiated."""
        from connectors.google_photos import PhotosConnector
        
        connector = PhotosConnector()
        self.assertIsNotNone(connector)
    
    def test_connector_has_required_methods(self):
        """Test connector has required methods."""
        from connectors.google_photos import PhotosConnector
        
        connector = PhotosConnector()
        
        self.assertTrue(hasattr(connector, 'connect'))
        self.assertTrue(hasattr(connector, 'list_albums'))
        self.assertTrue(hasattr(connector, 'get_album'))
        self.assertTrue(hasattr(connector, 'create_album'))
        self.assertTrue(hasattr(connector, 'search'))


# ============================================================================
# OneNote Tests
# ============================================================================

class TestOneNoteConnector(unittest.TestCase):
    """Tests for OneNoteConnector."""
    
    def test_import(self):
        """Test connector can be imported."""
        from connectors.onenote import OneNoteConnector, Notebook, Section, Page
        self.assertIsNotNone(OneNoteConnector)
    
    def test_notebook_dataclass(self):
        """Test Notebook data class."""
        from connectors.onenote import Notebook
        
        notebook = Notebook(
            id="nb123",
            display_name="Work Notes",
            created=datetime.now(),
            modified=datetime.now(),
        )
        
        self.assertEqual(notebook.id, "nb123")
        self.assertEqual(notebook.display_name, "Work Notes")
        
        d = notebook.to_dict()
        self.assertIn("id", d)
        self.assertIn("name", d)  # Uses 'name' as the key
    
    def test_section_dataclass(self):
        """Test Section data class."""
        from connectors.onenote import Section
        
        section = Section(
            id="sec123",
            display_name="Meeting Notes",
            parent_notebook_id="nb123",
            created=datetime.now(),
            modified=datetime.now(),
        )
        
        self.assertEqual(section.id, "sec123")
        self.assertEqual(section.display_name, "Meeting Notes")
        
        d = section.to_dict()
        self.assertIn("id", d)
        self.assertIn("name", d)
    
    def test_page_dataclass(self):
        """Test Page data class."""
        from connectors.onenote import Page
        
        page = Page(
            id="page123",
            title="Daily Standup",
            parent_section_id="sec123",
            created=datetime.now(),
            modified=datetime.now(),
        )
        
        self.assertEqual(page.id, "page123")
        self.assertEqual(page.title, "Daily Standup")
        
        d = page.to_dict()
        self.assertIn("id", d)
        self.assertIn("title", d)
    
    def test_connector_instantiation(self):
        """Test connector can be instantiated."""
        from connectors.onenote import OneNoteConnector
        
        connector = OneNoteConnector()
        self.assertFalse(connector.connected)
    
    def test_connector_has_required_methods(self):
        """Test connector has required methods."""
        from connectors.onenote import OneNoteConnector
        
        connector = OneNoteConnector()
        
        self.assertTrue(hasattr(connector, 'connect'))
        self.assertTrue(hasattr(connector, 'list_notebooks'))
        self.assertTrue(hasattr(connector, 'list_sections'))
        self.assertTrue(hasattr(connector, 'list_pages'))
        self.assertTrue(hasattr(connector, 'create_page'))
        self.assertTrue(hasattr(connector, 'get_page_content'))


# ============================================================================
# Twitter Tests
# ============================================================================

class TestTwitterConnector(unittest.TestCase):
    """Tests for TwitterConnector."""
    
    def test_import(self):
        """Test connector can be imported."""
        from connectors.twitter import TwitterConnector, Tweet, User
        self.assertIsNotNone(TwitterConnector)
    
    def test_tweet_dataclass(self):
        """Test Tweet data class."""
        from connectors.twitter import Tweet
        
        tweet = Tweet(
            id="tweet123",
            text="Hello, world!",
            author_id="user123",
            created_at=datetime.now(),
            public_metrics={"like_count": 50, "retweet_count": 10, "reply_count": 5},
        )
        
        self.assertEqual(tweet.id, "tweet123")
        self.assertEqual(tweet.text, "Hello, world!")
        self.assertEqual(tweet.likes, 50)
        self.assertEqual(tweet.retweets, 10)
        
        d = tweet.to_dict()
        self.assertIn("id", d)
        self.assertIn("text", d)
    
    def test_user_dataclass(self):
        """Test User data class."""
        from connectors.twitter import User
        
        user = User(
            id="user123",
            username="testuser",
            name="Test User",
            verified=False,
            public_metrics={"followers_count": 1000, "following_count": 500, "tweet_count": 250},
        )
        
        self.assertEqual(user.id, "user123")
        self.assertEqual(user.username, "testuser")
        self.assertEqual(user.followers, 1000)
        
        d = user.to_dict()
        self.assertIn("id", d)
        self.assertIn("username", d)
    
    def test_connector_instantiation(self):
        """Test connector can be instantiated."""
        from connectors.twitter import TwitterConnector
        
        connector = TwitterConnector()
        self.assertFalse(connector.connected)
    
    def test_connector_has_required_methods(self):
        """Test connector has required methods."""
        from connectors.twitter import TwitterConnector
        
        connector = TwitterConnector()
        
        self.assertTrue(hasattr(connector, 'connect'))
        self.assertTrue(hasattr(connector, 'post_tweet'))
        self.assertTrue(hasattr(connector, 'delete_tweet'))
        self.assertTrue(hasattr(connector, 'get_tweet'))
        self.assertTrue(hasattr(connector, 'search'))  # search, not search_tweets
        self.assertTrue(hasattr(connector, 'get_user'))
        self.assertTrue(hasattr(connector, 'get_user_tweets'))  # timeline
        self.assertTrue(hasattr(connector, 'like_tweet'))
        self.assertTrue(hasattr(connector, 'retweet'))


# ============================================================================
# SmartThings Tests
# ============================================================================

class TestSmartThingsConnector(unittest.TestCase):
    """Tests for SmartThingsConnector."""
    
    def test_import(self):
        """Test connector can be imported."""
        from connectors.smartthings import SmartThingsConnector, Device, Location, Scene
        self.assertIsNotNone(SmartThingsConnector)
    
    def test_device_dataclass(self):
        """Test Device data class."""
        from connectors.smartthings import Device, DeviceCategory
        
        device = Device(
            id="dev123",
            name="Living Room Light",
            label="Main Light",
            device_type_name="Light",
            location_id="loc123",
            room_id="room123",
            capabilities=["switch", "switchLevel", "colorControl"],
            category=DeviceCategory.LIGHT,
            manufacturer="Philips",
        )
        
        self.assertEqual(device.id, "dev123")
        self.assertEqual(device.name, "Living Room Light")
        self.assertEqual(device.display_name, "Main Light")
        self.assertTrue(device.has_capability("switch"))
        self.assertFalse(device.has_capability("lock"))
        
        d = device.to_dict()
        self.assertIn("id", d)
        self.assertIn("name", d)
        self.assertIn("capabilities", d)
    
    def test_location_dataclass(self):
        """Test Location data class."""
        from connectors.smartthings import Location
        
        location = Location(
            id="loc123",
            name="Home",
            country_code="US",
            timezone_id="America/New_York",
            latitude=40.7128,
            longitude=-74.0060,
        )
        
        self.assertEqual(location.id, "loc123")
        self.assertEqual(location.name, "Home")
        
        d = location.to_dict()
        self.assertIn("id", d)
        self.assertIn("name", d)
    
    def test_scene_dataclass(self):
        """Test Scene data class."""
        from connectors.smartthings import Scene
        
        scene = Scene(
            id="scene123",
            name="Movie Night",
            location_id="loc123",
            icon="movie",
            color="#FF5733",
        )
        
        self.assertEqual(scene.id, "scene123")
        self.assertEqual(scene.name, "Movie Night")
        
        d = scene.to_dict()
        self.assertIn("id", d)
        self.assertIn("name", d)
    
    def test_connector_instantiation(self):
        """Test connector can be instantiated."""
        from connectors.smartthings import SmartThingsConnector
        
        connector = SmartThingsConnector()
        self.assertFalse(connector.is_connected)
    
    def test_connector_has_required_methods(self):
        """Test connector has required methods."""
        from connectors.smartthings import SmartThingsConnector
        
        connector = SmartThingsConnector()
        
        self.assertTrue(hasattr(connector, 'connect'))
        self.assertTrue(hasattr(connector, 'disconnect'))
        self.assertTrue(hasattr(connector, 'list_locations'))
        self.assertTrue(hasattr(connector, 'list_devices'))
        self.assertTrue(hasattr(connector, 'get_device'))
        self.assertTrue(hasattr(connector, 'get_device_status'))
        self.assertTrue(hasattr(connector, 'execute_command'))
        self.assertTrue(hasattr(connector, 'turn_on'))
        self.assertTrue(hasattr(connector, 'turn_off'))
        self.assertTrue(hasattr(connector, 'set_level'))
        self.assertTrue(hasattr(connector, 'list_scenes'))
        self.assertTrue(hasattr(connector, 'execute_scene'))
    
    def test_device_categories(self):
        """Test DeviceCategory enum."""
        from connectors.smartthings import DeviceCategory
        
        self.assertEqual(DeviceCategory.LIGHT.value, "Light")
        self.assertEqual(DeviceCategory.SWITCH.value, "Switch")
        self.assertEqual(DeviceCategory.THERMOSTAT.value, "Thermostat")
        self.assertEqual(DeviceCategory.LOCK.value, "Lock")
    
    def test_capability_types(self):
        """Test CapabilityType enum."""
        from connectors.smartthings import CapabilityType
        
        self.assertEqual(CapabilityType.SWITCH.value, "switch")
        self.assertEqual(CapabilityType.SWITCH_LEVEL.value, "switchLevel")
        self.assertEqual(CapabilityType.COLOR_CONTROL.value, "colorControl")
        self.assertEqual(CapabilityType.LOCK.value, "lock")


# ============================================================================
# Registry Integration Tests
# ============================================================================

class TestConnectorRegistration(unittest.TestCase):
    """Tests for connector registration in registry."""
    
    def test_google_sheets_registered(self):
        """Test Google Sheets is registered."""
        from connectors.registry import get_registry, reset_registry
        reset_registry()
        registry = get_registry()
        
        metadata = registry.get_metadata("google_sheets")
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.provider, "google")
        self.assertIn("SPREADSHEET", metadata.primitives)
    
    def test_google_slides_registered(self):
        """Test Google Slides is registered."""
        from connectors.registry import get_registry, reset_registry
        reset_registry()
        registry = get_registry()
        
        metadata = registry.get_metadata("google_slides")
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.provider, "google")
        self.assertIn("PRESENTATION", metadata.primitives)
    
    def test_google_photos_registered(self):
        """Test Google Photos is registered."""
        from connectors.registry import get_registry, reset_registry
        reset_registry()
        registry = get_registry()
        
        metadata = registry.get_metadata("google_photos")
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.provider, "google")
        self.assertIn("PHOTO", metadata.primitives)
    
    def test_onenote_registered(self):
        """Test OneNote is registered."""
        from connectors.registry import get_registry, reset_registry
        reset_registry()
        registry = get_registry()
        
        metadata = registry.get_metadata("onenote")
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.provider, "microsoft")
        self.assertIn("NOTES", metadata.primitives)
    
    def test_twitter_registered(self):
        """Test Twitter is registered."""
        from connectors.registry import get_registry, reset_registry
        reset_registry()
        registry = get_registry()
        
        metadata = registry.get_metadata("twitter")
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.provider, "twitter")
        self.assertIn("SOCIAL", metadata.primitives)
    
    def test_smartthings_registered(self):
        """Test SmartThings is registered."""
        from connectors.registry import get_registry, reset_registry
        reset_registry()
        registry = get_registry()
        
        metadata = registry.get_metadata("smartthings")
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.provider, "smartthings")
        self.assertIn("IOT", metadata.primitives)
        self.assertIn("HOME_AUTOMATION", metadata.primitives)
    
    def test_primitives_have_connectors(self):
        """Test new primitives are mapped to connectors."""
        from connectors.registry import get_registry, reset_registry
        reset_registry()
        registry = get_registry()
        
        # Check each new primitive has connectors
        # get_providers_for_primitive returns connector names, not provider names
        spreadsheet_connectors = registry.get_providers_for_primitive("SPREADSHEET")
        self.assertIn("google_sheets", spreadsheet_connectors)
        
        presentation_connectors = registry.get_providers_for_primitive("PRESENTATION")
        self.assertIn("google_slides", presentation_connectors)
        
        photo_connectors = registry.get_providers_for_primitive("PHOTO")
        self.assertIn("google_photos", photo_connectors)
        
        notes_connectors = registry.get_providers_for_primitive("NOTES")
        self.assertIn("onenote", notes_connectors)
        
        social_connectors = registry.get_providers_for_primitive("SOCIAL")
        self.assertIn("twitter", social_connectors)
        
        iot_connectors = registry.get_providers_for_primitive("IOT")
        self.assertIn("smartthings", iot_connectors)


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    # Run with verbosity
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestGoogleSheetsConnector))
    suite.addTests(loader.loadTestsFromTestCase(TestGoogleSlidesConnector))
    suite.addTests(loader.loadTestsFromTestCase(TestGooglePhotosConnector))
    suite.addTests(loader.loadTestsFromTestCase(TestOneNoteConnector))
    suite.addTests(loader.loadTestsFromTestCase(TestTwitterConnector))
    suite.addTests(loader.loadTestsFromTestCase(TestSmartThingsConnector))
    suite.addTests(loader.loadTestsFromTestCase(TestConnectorRegistration))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"Total tests: {result.testsRun}")
    print(f"Passed: {result.testsRun - len(result.failures) - len(result.errors)} ({100 * (result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun:.1f}%)")
    print(f"Failed: {len(result.failures)} ({100 * len(result.failures) / result.testsRun:.1f}%)")
    print(f"Errors: {len(result.errors)}")
    print("=" * 70)
    
    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)
