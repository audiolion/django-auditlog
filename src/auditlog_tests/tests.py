import datetime
from django.contrib.auth.models import User, AnonymousUser
from django.core.exceptions import ValidationError
from django.db.models.signals import pre_save
from django.http import HttpResponse
from django.test import TestCase, RequestFactory
from django.utils import timezone

from auditlog.middleware import AuditlogMiddleware
from auditlog.models import LogEntry
from auditlog.registry import auditlog
from auditlog_tests.models import SimpleModel, AltPrimaryKeyModel, ProxyModel, \
    SimpleIncludeModel, SimpleExcludeModel, SimpleMappingModel, RelatedModel, ManyRelatedModel, \
    AdditionalDataIncludedModel, DateTimeFieldModel, ChoicesFieldModel, CharfieldTextfieldModel


class SimpleModelTest(TestCase):
    def setUp(self):
        self.obj = SimpleModel.objects.create(text='I am not difficult.')

    def test_create(self):
        """Creation is logged correctly."""
        # Get the object to work with
        obj = self.obj

        # Check for log entries
        self.assertTrue(obj.history.count() == 1, msg="There is one log entry")

        try:
            history = obj.history.get()
        except obj.history.DoesNotExist:
            self.assertTrue(False, "Log entry exists")
        else:
            self.assertEqual(history.action, LogEntry.Action.CREATE, msg="Action is 'CREATE'")
            self.assertEqual(history.object_repr, str(obj), msg="Representation is equal")

    def test_update(self):
        """Updates are logged correctly."""
        # Get the object to work with
        obj = self.obj

        # Change something
        obj.boolean = True
        obj.save()

        # Check for log entries
        self.assertTrue(obj.history.filter(action=LogEntry.Action.UPDATE).count() == 1, msg="There is one log entry for 'UPDATE'")

        history = obj.history.get(action=LogEntry.Action.UPDATE)

        self.assertJSONEqual(history.changes, '{"boolean": ["False", "True"]}', msg="The change is correctly logged")

    def test_delete(self):
        """Deletion is logged correctly."""
        # Get the object to work with
        obj = self.obj

        history = obj.history.latest()

        # Delete the object
        obj.delete()

        # Check for log entries
        self.assertTrue(LogEntry.objects.filter(content_type=history.content_type, object_pk=history.object_pk, action=LogEntry.Action.DELETE).count() == 1, msg="There is one log entry for 'DELETE'")

    def test_recreate(self):
        SimpleModel.objects.all().delete()
        self.setUp()
        self.test_create()


class AltPrimaryKeyModelTest(SimpleModelTest):
    def setUp(self):
        self.obj = AltPrimaryKeyModel.objects.create(key=str(datetime.datetime.now()), text='I am strange.')


class ProxyModelTest(SimpleModelTest):
    def setUp(self):
        self.obj = ProxyModel.objects.create(text='I am not what you think.')


class ManyRelatedModelTest(TestCase):
    """
    Test the behaviour of a many-to-many relationship.
    """
    def setUp(self):
        self.obj = ManyRelatedModel.objects.create()
        self.rel_obj = ManyRelatedModel.objects.create()
        self.obj.related.add(self.rel_obj)

    def test_related(self):
        self.assertEqual(LogEntry.objects.get_for_objects(self.obj.related.all()).count(), self.rel_obj.history.count())
        self.assertEqual(LogEntry.objects.get_for_objects(self.obj.related.all()).first(), self.rel_obj.history.first())


class MiddlewareTest(TestCase):
    """
    Test the middleware responsible for connecting and disconnecting the signals used in automatic logging.
    """
    def setUp(self):
        self.middleware = AuditlogMiddleware()
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username='test', email='test@example.com', password='top_secret')

    def test_request_anonymous(self):
        """No actor will be logged when a user is not logged in."""
        # Create a request
        request = self.factory.get('/')
        request.user = AnonymousUser()

        # Run middleware
        self.middleware.process_request(request)

        # Validate result
        self.assertFalse(pre_save.has_listeners(LogEntry))

        # Finalize transaction
        self.middleware.process_exception(request, None)

    def test_request(self):
        """The actor will be logged when a user is logged in."""
        # Create a request
        request = self.factory.get('/')
        request.user = self.user
        # Run middleware
        self.middleware.process_request(request)

        # Validate result
        self.assertTrue(pre_save.has_listeners(LogEntry))

        # Finalize transaction
        self.middleware.process_exception(request, None)

    def test_response(self):
        """The signal will be disconnected when the request is processed."""
        # Create a request
        request = self.factory.get('/')
        request.user = self.user

        # Run middleware
        self.middleware.process_request(request)
        self.assertTrue(pre_save.has_listeners(LogEntry))  # The signal should be present before trying to disconnect it.
        self.middleware.process_response(request, HttpResponse())

        # Validate result
        self.assertFalse(pre_save.has_listeners(LogEntry))

    def test_exception(self):
        """The signal will be disconnected when an exception is raised."""
        # Create a request
        request = self.factory.get('/')
        request.user = self.user

        # Run middleware
        self.middleware.process_request(request)
        self.assertTrue(pre_save.has_listeners(LogEntry))  # The signal should be present before trying to disconnect it.
        self.middleware.process_exception(request, ValidationError("Test"))

        # Validate result
        self.assertFalse(pre_save.has_listeners(LogEntry))


class SimpeIncludeModelTest(TestCase):
    """Log only changes in include_fields"""

    def test_register_include_fields(self):
        sim = SimpleIncludeModel(label='Include model', text='Looong text')
        sim.save()
        self.assertTrue(sim.history.count() == 1, msg="There is one log entry")

        # Change label, record
        sim.label = 'Changed label'
        sim.save()
        self.assertTrue(sim.history.count() == 2, msg="There are two log entries")

        # Change text, ignore
        sim.text = 'Short text'
        sim.save()
        self.assertTrue(sim.history.count() == 2, msg="There are two log entries")


class SimpeExcludeModelTest(TestCase):
    """Log only changes that are not in exclude_fields"""

    def test_register_exclude_fields(self):
        sem = SimpleExcludeModel(label='Exclude model', text='Looong text')
        sem.save()
        self.assertTrue(sem.history.count() == 1, msg="There is one log entry")

        # Change label, ignore
        sem.label = 'Changed label'
        sem.save()
        self.assertTrue(sem.history.count() == 2, msg="There are two log entries")

        # Change text, record
        sem.text = 'Short text'
        sem.save()
        self.assertTrue(sem.history.count() == 2, msg="There are two log entries")


class SimpleMappingModelTest(TestCase):
    """Diff displays fields as mapped field names where available through mapping_fields"""

    def test_register_mapping_fields(self):
        smm = SimpleMappingModel(sku='ASD301301A6', vtxt='2.1.5', not_mapped='Not mapped')
        smm.save()
        self.assertTrue(smm.history.latest().changes_dict['Product No.'][1] == 'ASD301301A6',
                        msg="The diff function maps 'sku' as 'Product No.' and can be retrieved.")
        self.assertTrue(smm.history.latest().changes_dict['not_mapped'][1] == 'Not mapped',
                        msg="The diff function does not map 'not_mapped' and can be retrieved.")
        self.assertTrue(smm.history.latest().changes_display_dict['Product No.'][1] == 'ASD301301A6',
                        msg="The diff function maps 'sku' as 'Product No.' and can be retrieved.")
        self.assertTrue(smm.history.latest().changes_display_dict['not_mapped'][1] == 'Not mapped',
                        msg="The diff function does not map 'not_mapped' and can be retrieved.")


class AdditionalDataModelTest(TestCase):
    """Log additional data if get_additional_data is defined in the model"""

    def test_model_without_additional_data(self):
        obj_wo_additional_data = SimpleModel.objects.create(text='No additional '
                                                                 'data')
        obj_log_entry = obj_wo_additional_data.history.get()
        self.assertIsNone(obj_log_entry.additional_data)

    def test_model_with_additional_data(self):
        related_model = SimpleModel.objects.create(text='Log my reference')
        obj_with_additional_data = AdditionalDataIncludedModel(
            label='Additional data to log entries', related=related_model)
        obj_with_additional_data.save()
        self.assertTrue(obj_with_additional_data.history.count() == 1,
                        msg="There is 1 log entry")
        log_entry = obj_with_additional_data.history.get()
        self.assertIsNotNone(log_entry.additional_data)
        extra_data = log_entry.additional_data
        self.assertTrue(extra_data['related_model_text'] == related_model.text,
                        msg="Related model's text is logged")
        self.assertTrue(extra_data['related_model_id'] == related_model.id,
                        msg="Related model's id is logged")


class DateTimeFieldModelTest(TestCase):
    """Tests if DateTimeField changes are recognised correctly"""

    utc_plus_one = timezone.get_fixed_timezone(datetime.timedelta(hours=1))

    def test_model_with_same_time(self):
        timestamp = datetime.datetime(2017, 1, 10, 12, 0, tzinfo=timezone.utc)
        dtm = DateTimeFieldModel(label='DateTimeField model', timestamp=timestamp)
        dtm.save()
        self.assertTrue(dtm.history.count() == 1, msg="There is one log entry")

        # Change timestamp to same datetime and timezone
        timestamp = datetime.datetime(2017, 1, 10, 12, 0, tzinfo=timezone.utc)
        dtm.timestamp = timestamp
        dtm.save()

        # Nothing should have changed
        self.assertTrue(dtm.history.count() == 1, msg="There is one log entry")

    def test_model_with_different_timezone(self):
        timestamp = datetime.datetime(2017, 1, 10, 12, 0, tzinfo=timezone.utc)
        dtm = DateTimeFieldModel(label='DateTimeField model', timestamp=timestamp)
        dtm.save()
        self.assertTrue(dtm.history.count() == 1, msg="There is one log entry")

        # Change timestamp to same datetime in another timezone
        timestamp = datetime.datetime(2017, 1, 10, 13, 0, tzinfo=self.utc_plus_one)
        dtm.timestamp = timestamp
        dtm.save()

        # Nothing should have changed
        self.assertTrue(dtm.history.count() == 1, msg="There is one log entry")

    def test_model_with_different_time(self):
        timestamp = datetime.datetime(2017, 1, 10, 12, 0, tzinfo=timezone.utc)
        dtm = DateTimeFieldModel(label='DateTimeField model', timestamp=timestamp)
        dtm.save()
        self.assertTrue(dtm.history.count() == 1, msg="There is one log entry")

        # Change timestamp to another datetime in the same timezone
        timestamp = datetime.datetime(2017, 1, 10, 13, 0, tzinfo=timezone.utc)
        dtm.timestamp = timestamp
        dtm.save()

        # The time should have changed.
        self.assertTrue(dtm.history.count() == 2, msg="There are two log entries")

    def test_model_with_different_time_and_timezone(self):
        timestamp = datetime.datetime(2017, 1, 10, 12, 0, tzinfo=timezone.utc)
        dtm = DateTimeFieldModel(label='DateTimeField model', timestamp=timestamp)
        dtm.save()
        self.assertTrue(dtm.history.count() == 1, msg="There is one log entry")

        # Change timestamp to another datetime and another timezone
        timestamp = datetime.datetime(2017, 1, 10, 14, 0, tzinfo=self.utc_plus_one)
        dtm.timestamp = timestamp
        dtm.save()

        # The time should have changed.
        self.assertTrue(dtm.history.count() == 2, msg="There are two log entries")

    def test_changes_display_dict_datetime(self):
        timestamp = datetime.datetime(2017, 1, 10, 15, 0, tzinfo=timezone.utc)
        dtm = DateTimeFieldModel(label='DateTimeField model', timestamp=timestamp)
        dtm.save()
        self.assertTrue(dtm.history.latest().changes_display_dict["timestamp"][1] == \
                        timestamp.strftime("%b %d, %Y %I:%M %p"),
                        msg="The datetime should be formatted in a human readable way.")
        timestamp = timezone.now()
        dtm.timestamp = timestamp
        dtm.save()
        self.assertTrue(dtm.history.latest().changes_display_dict["timestamp"][1] == \
                        timestamp.strftime("%b %d, %Y %I:%M %p"),
                        msg="The datetime should be formatted in a human readable way.")


class UnregisterTest(TestCase):
    def setUp(self):
        auditlog.unregister(SimpleModel)
        self.obj = SimpleModel.objects.create(text='No history')

    def tearDown(self):
        # Re-register for future tests
        auditlog.register(SimpleModel)

    def test_unregister_create(self):
        """Creation is not logged after unregistering."""
        # Get the object to work with
        obj = self.obj

        # Check for log entries
        self.assertTrue(obj.history.count() == 0, msg="There are no log entries")

    def test_unregister_update(self):
        """Updates are not logged after unregistering."""
        # Get the object to work with
        obj = self.obj

        # Change something
        obj.boolean = True
        obj.save()

        # Check for log entries
        self.assertTrue(obj.history.count() == 0, msg="There are no log entries")

    def test_unregister_delete(self):
        """Deletion is not logged after unregistering."""
        # Get the object to work with
        obj = self.obj

        # Delete the object
        obj.delete()

        # Check for log entries
        self.assertTrue(LogEntry.objects.count() == 0, msg="There are no log entries")


class ChoicesFieldModelTest(TestCase):

    def setUp(self):
        self.obj = ChoicesFieldModel.objects.create(
            status=ChoicesFieldModel.RED,
            multiselect=[ChoicesFieldModel.RED, ChoicesFieldModel.GREEN],
            multiplechoice=[ChoicesFieldModel.RED, ChoicesFieldModel.YELLOW, ChoicesFieldModel.GREEN],
        )

    def test_changes_display_dict_single_choice(self):

        self.assertTrue(self.obj.history.latest().changes_display_dict["status"][1] == "Red",
                        msg="The human readable text 'Red' is displayed.")
        self.obj.status = ChoicesFieldModel.GREEN
        self.obj.save()
        self.assertTrue(self.obj.history.latest().changes_display_dict["status"][1] == "Green", msg="The human readable text 'Green' is displayed.")

    def test_changes_display_dict_multiselect(self):
        self.assertTrue(self.obj.history.latest().changes_display_dict["multiselect"][1] == "Red, Green",
                        msg="The human readable text for the two choices, 'Red, Green' is displayed.")
        self.obj.multiselect = ChoicesFieldModel.GREEN
        self.obj.save()
        self.assertTrue(self.obj.history.latest().changes_display_dict["multiselect"][1] == "Green",
                        msg="The human readable text 'Green' is displayed.")
        self.obj.multiselect = None
        self.obj.save()
        self.assertTrue(self.obj.history.latest().changes_display_dict["multiselect"][1] == "None",
                        msg="The human readable text 'None' is displayed.")
        self.obj.multiselect = ChoicesFieldModel.GREEN
        self.obj.save()
        self.assertTrue(self.obj.history.latest().changes_display_dict["multiselect"][1] == "Green",
                        msg="The human readable text 'Green' is displayed.")

    def test_changes_display_dict_multiplechoice(self):
        self.assertTrue(self.obj.history.latest().changes_display_dict["multiplechoice"][1] == "Red, Yellow, Green",
                        msg="The human readable text 'Red, Yellow, Green' is displayed.")
        self.obj.multiplechoice = ChoicesFieldModel.RED
        self.obj.save()
        self.assertTrue(self.obj.history.latest().changes_display_dict["multiplechoice"][1] == "Red",
                        msg="The human readable text 'Red' is displayed.")


class CharfieldTextfieldModelTest(TestCase):

    def setUp(self):
        self.PLACEHOLDER_LONGCHAR = "s" * 255
        self.PLACEHOLDER_LONGTEXTFIELD = "s" * 1000
        self.obj = CharfieldTextfieldModel.objects.create(
            longchar=self.PLACEHOLDER_LONGCHAR,
            longtextfield=self.PLACEHOLDER_LONGTEXTFIELD,
        )

    def test_changes_display_dict_longchar(self):
        self.assertTrue(self.obj.history.latest().changes_display_dict["longchar"][1] == \
                        "{}...".format(self.PLACEHOLDER_LONGCHAR[:140]),
                        msg="The string should be truncated at 140 characters with an ellipsis at the end.")
        SHORTENED_PLACEHOLDER = self.PLACEHOLDER_LONGCHAR[:139]
        self.obj.longchar = SHORTENED_PLACEHOLDER
        self.obj.save()
        self.assertTrue(self.obj.history.latest().changes_display_dict["longchar"][1] == SHORTENED_PLACEHOLDER,
                        msg="The field should display the entire string because it is less than 140 characters")

    def test_changes_display_dict_longtextfield(self):
        self.assertTrue(self.obj.history.latest().changes_display_dict["longtextfield"][1] == \
                "{}...".format(self.PLACEHOLDER_LONGTEXTFIELD[:140]),
                msg="The string should be truncated at 140 characters with an ellipsis at the end.")
        SHORTENED_PLACEHOLDER = self.PLACEHOLDER_LONGTEXTFIELD[:139]
        self.obj.longtextfield = SHORTENED_PLACEHOLDER
        self.obj.save()
        self.assertTrue(self.obj.history.latest().changes_display_dict["longtextfield"][1] == SHORTENED_PLACEHOLDER,
                        msg="The field should display the entire string because it is less than 140 characters")
