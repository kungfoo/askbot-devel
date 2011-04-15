from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from django.test import TestCase
from django.utils import simplejson

from categories.models import Category

from askbot.conf import settings as askbot_settings
from askbot.models import Tag
from askbot.views.cats import generate_tree


class TreeTests(TestCase):
    def setUp(self):
        root = Category.objects.create(name='Root')
        n1 = Category.objects.create(name='N1', parent=root)
        Category.objects.create(name='N2', parent=root)
        Category.objects.create(name='Child1', parent=n1)
        Category.objects.create(name='Child2', parent=n1)

    def test_python_tree(self):
        """
        Test that django-mptt builds the tree correctly. version 0.4.2 has a
        bug when populating the tree, it incorrectly grafts the Child1 and
        Child2 nodes under N2.
        """
        self.assertEqual(
            {
                "name": u"Root",
                "id": (1, 1),
                "children": [
                    {
                        "name": u"N1",
                        "id": (1, 2),
                        "children": [
                            {
                                "name": u"Child1",
                                "id": (1, 3),
                                "children": []
                            },
                            {
                                "name": u"Child2",
                                "id": (1, 5),
                                "children": []
                            }
                        ]
                    },
                    {
                        "name": u"N2",
                        "id": (1, 8),
                        "children": []
                    }

                ]
            },
            generate_tree()
        )


class EmptyTreeTests(TestCase):
    def test_python_tree(self):
        """Data structure generation shouldn't explode when tree is empty."""
        self.assertEqual({}, generate_tree())


class AjaxTests(TestCase):
    def ajax_get(self, path, data={}, follow=False, **extra):
        extra.update({'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'})
        return self.client(path, data, follow, **extra)

    def ajax_post(self, path, data={}, content_type='application/x-www-form-urlencoded', follow=False,
            **extra):
        extra.update({'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'})
        return self.client.post(path, data, content_type, follow, **extra)

    def ajax_post_json(self, path, data):
        return self.ajax_post(path, simplejson.dumps(data))

    def assertAjaxSuccess(self, response):
        try:
            data = simplejson.loads(response.content)
        except Exception, e:
            self.fail(str(e))
        self.assertTrue(data['success'])


class ViewsTests(AjaxTests):
    def setUp(self):
        # An administrator user
        self.owner = User.objects.create_user(username='owner', email='owner@example.com', password='secret')
        self.owner.is_staff = True
        self.owner.is_superuser = True
        self.owner.save()
        # A normal user
        User.objects.create_user(username='user1', email='user1@example.com', password='123')
        # Setup a small category tree
        root = Category.objects.create(name=u'Root')
        self.c1 = Category.objects.create(name=u'Child1', parent=root)

        self.tag1 = Tag.objects.create(name=u'Tag1', created_by=self.owner)
        self.tag2 = Tag.objects.create(name=u'Tag2', created_by=self.owner)
        self.tag2.categories.add(self.c1)

        askbot_settings.update('ENABLE_CATEGORIES', True)

    #def test_categories_off(self):
    #    """AJAX category-related views shouldn't exist when master switch is off."""
    #    askbot_settings.update('ENABLE_CATEGORIES', False)
    #    r = self.ajax_post_json(reverse('add_category'), {'name': u'Entertainment', 'parent': (1, 1)})
    #    self.assertEqual(r.status_code, 404)
    #    askbot_settings.update('ENABLE_CATEGORIES', True)
    #    r = self.ajax_post_json(reverse('add_category'), {'name': u'Family', 'parent': (1, 1)})
    #    self.assertEqual(r.status_code, 404)

    def test_add_category_no_permission(self):
        """Only administrator users should be able to add a category via the view."""
        self.client.login(username='user1', password='123')
        r = self.ajax_post_json(reverse('add_category'), {'name': u'Health', 'parent': (1, 1)})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        self.assertContains(r, 'Sorry, but you cannot access this view')

    def test_add_missing_param(self):
        """Add new category: should fail when no name parameter is provided."""
        self.client.login(username='owner', password='secret')
        r = self.ajax_post_json(reverse('add_category'), {})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        self.assertContains(r, "Missing or invalid new category name parameter")

    def test_add_category_exists(self):
        """Two categories with the same name shouldn't be allowed."""
        self.client.login(username='owner', password='secret')
        r = self.ajax_post_json(reverse('add_category'), {'name': u'Child1', 'parent': (1, 1)})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        self.assertContains(r, 'There is already a category with that name')

    def add_category_success(self, post_data):
        """Helper method"""
        category_objects = Category.objects.count()
        r = self.ajax_post_json(reverse('add_category'), post_data)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        self.assertAjaxSuccess(r)
        self.assertEqual(category_objects + 1, Category.objects.count())

    def test_add_category_success(self):
        """Valid new categories should be added to the database."""
        self.client.login(username='owner', password='secret')
        # A child of the root node
        self.add_category_success({'name': u'Child2', 'parent': (1, 1)})
        # A child of a non-root node
        self.add_category_success({'name': u'Child1', 'parent': (self.c1.tree_id, self.c1.lft)})

    def test_add_new_tree(self):
        """Test insertion of a new root-of-tree node."""
        self.client.login(username='owner', password='secret')
        category_objects = Category.objects.count()
        r = self.ajax_post_json(reverse('add_category'), {'name': u'AnotherRoot', 'parent': None})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        self.assertAjaxSuccess(r)
        self.assertEqual(category_objects + 1, Category.objects.count())
        self.assertEqual(Category.tree.root_nodes().filter(name=u'AnotherRoot').count(), 1)

    def test_add_invalid_parent(self):
        """Attempts to insert a new category with an invalid parent should fail."""
        self.client.login(username='owner', password='secret')
        r = self.ajax_post_json(reverse('add_category'), {'name': u'Foo', 'parent': (100, 20)})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        self.assertContains(r, "Requested parent category doesn't exist")

    def test_rename_missing_params(self):
        """Rename category: should fail when no IDs are passed."""
        self.client.login(username='owner', password='secret')
        obj = Category.objects.get(name=u'Child1')
        obj_id = (obj.tree_id, obj.lft)
        r = self.ajax_post_json(reverse('rename_category'), {'id': obj_id})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        self.assertContains(r, "Missing or invalid required parameter")

        r = self.ajax_post_json(reverse('rename_category'), {'name': u'Foo'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        self.assertContains(r, "Missing or invalid required parameter")

    def test_rename_success(self):
        """Rename a category"""
        self.client.login(username='owner', password='secret')
        obj = Category.objects.get(name=u'Child1')
        obj_id = (obj.tree_id, obj.lft)
        r = self.ajax_post_json(reverse('rename_category'), {'id': obj_id, 'name': u'NewName'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        self.assertAjaxSuccess(r)
        # Re-fech the object from the DB
        obj = Category.objects.get(tree_id=obj_id[0], lft=obj_id[1])
        self.assertEqual(obj.name, u'NewName')

    def test_rename_exists(self):
        """Renaming to a name that already exists shouldn't be allowed."""
        self.client.login(username='owner', password='secret')
        r = self.ajax_post_json(reverse('rename_category'), {'id': (1, 1), 'name': u'Child1'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        self.assertContains(r, 'There is already a category with that name')

    def test_rename_invalid_id(self):
        """Attempts to rename a category with an invalid ID should fail."""
        self.client.login(username='owner', password='secret')
        r = self.ajax_post_json(reverse('rename_category'), {'id': (100, 20), 'name': u'NewName'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        self.assertContains(r, "Requested category doesn't exist")

    def test_tag_missing_params(self):
        """Add tag to category: should fail when no IDs are passed."""
        self.client.login(username='owner', password='secret')
        r = self.ajax_post_json(reverse('add_tag_to_category'), {'cat_id': (1, 1)})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        self.assertContains(r, "Missing required parameter")

        r = self.ajax_post_json(reverse('add_tag_to_category'), {'tag_id': self.tag1.id})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        self.assertContains(r, "Missing required parameter")

    def test_tag_invalid_ids(self):
        """Attempts to add a tag to a category using invalid IDs should fail."""
        self.client.login(username='owner', password='secret')
        r = self.ajax_post_json(
                reverse('add_tag_to_category'),
                {'cat_id': (1, 1), 'tag_id': 100})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        self.assertContains(r, "Requested tag doesn't exist")

        r = self.ajax_post_json(
                reverse('add_tag_to_category'),
                {'cat_id': (100, 20), 'tag_id': self.tag1.id})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        self.assertContains(r, "Requested category doesn't exist")

    def test_tag_success(self):
        """Adding a tag to a category."""
        self.client.login(username='owner', password='secret')
        associated_cats = self.tag1.categories.filter(tree_id=1, lft=1).count()
        r = self.ajax_post_json(
                reverse('add_tag_to_category'),
                {'cat_id': (1, 1), 'tag_id': self.tag1.id})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        self.assertAjaxSuccess(r)
        self.assertEqual(associated_cats + 1, self.tag1.categories.filter(tree_id=1, lft=1).count())

    def test_tag_categories_missing_param(self):
        """Get categories for tag: should fail when no tag ID is passed."""
        r = self.ajax_post_json(reverse('get_tag_categories'), {})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        self.assertContains(r, "Missing tag_id parameter")

    def test_tag_categories_invalid_id(self):
        """Get categories for tag: should fail when invalid tag ID is passed."""
        r = self.ajax_post_json(reverse('get_tag_categories'), {'tag_id': 100})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        self.assertContains(r, "Requested tag doesn't exist")

    def test_tag_categories_success(self):
        """Get categories for tag."""
        # Empty category set
        r = self.ajax_post_json(reverse('get_tag_categories'), {'tag_id': self.tag1.id})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        try:
            data = simplejson.loads(r.content)
        except Exception, e:
            self.fail(str(e))
        self.assertTrue(data['success'])
        self.assertEqual(len(data['cats']), 0)

        # Non-empty category set
        r = self.ajax_post_json(reverse('get_tag_categories'), {'tag_id': self.tag2.id})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        try:
            data = simplejson.loads(r.content)
        except Exception, e:
            self.fail(str(e))
        self.assertTrue(data['success'])
        self.assertEqual(data['cats'], [{'id': self.c1.id, 'name': self.c1.name}])

    # TODO: Test explicitly with anonymous user for get_tag_categories

    def test_remove_tag_category__no_permission(self):
        """Only administrator and moderator users should be able to remove a
        tag form a category via the view."""
        self.client.login(username='user1', password='123')
        r = self.ajax_post_json(
            reverse('remove_tag_from_category'),
            {
                'cat_id': (self.c1.tree_id, self.c1.lft),
                'tag_id': self.tag2.id
            }
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        self.assertContains(r, 'Sorry, but you cannot access this view')
        self.client.logout()
        # TODO: test with a moderator user

    def test_remove_tag_category_missing_params(self):
        """Remove tag from category: should fail when no IDs are passed."""
        self.client.login(username='owner', password='secret')
        r = self.ajax_post_json(reverse('remove_tag_from_category'),
                {'tag_id': self.tag2.id})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        self.assertContains(r, "Missing required parameter")

        r = self.ajax_post_json(reverse('remove_tag_from_category'),
                {'cat_id': (self.c1.tree_id, self.c1.lft)})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        self.assertContains(r, "Missing required parameter")

    def test_remove_tag_category_success(self):
        """Remove tag from category: should fail when no IDs are passed."""
        self.client.login(username='owner', password='secret')
        r = self.ajax_post_json(
            reverse('remove_tag_from_category'),
            {
                'cat_id': (self.c1.tree_id, self.c1.lft),
                'tag_id': self.tag2.id
            }
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        self.assertAjaxSuccess(r)

    def test_remove_tag_category_invalid_params(self):
        """Remove tag from category: should fail when invalid IDs are passed."""
        self.client.login(username='owner', password='secret')
        r = self.ajax_post_json(
            reverse('remove_tag_from_category'),
            {
                'cat_id': (100, 20),
                'tag_id': self.tag2.id
            }
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        self.assertContains(r, "Requested category doesn't exist")

        r = self.ajax_post_json(
            reverse('remove_tag_from_category'),
            {
                'cat_id': (self.c1.tree_id, self.c1.lft),
                'tag_id': 1000
            }
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/json')
        self.assertContains(r, "Requested tag doesn't exist")