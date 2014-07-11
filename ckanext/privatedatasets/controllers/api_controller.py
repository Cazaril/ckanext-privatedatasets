import ckan.lib.base as base
import ckan.lib.helpers as helpers
import ckan.model as model
import ckan.plugins as plugins
import ckanext.privatedatasets.constants as constants
import ckanext.privatedatasets.db as db
import importlib
import logging
import pylons.config as config

from ckan.common import response

log = logging.getLogger(__name__)

PARSER_CONFIG_PROP = 'ckan.privatedatasets.parser'


######################################################################
############################ API CONTROLLER ##########################
######################################################################

class AdquiredDatasetsControllerAPI(base.BaseController):

    def __call__(self, environ, start_response):
        # avoid status_code_redirect intercepting error responses
        environ['pylons.status_code_redirect'] = True
        return base.BaseController.__call__(self, environ, start_response)

    def add_users(self):

        log.info('Notification Request received')

        if db.package_allowed_users_table is None:
            db.init_db(model)

        # Get the parser from the configuration
        class_path = config.get(PARSER_CONFIG_PROP, '')

        if class_path != '':
            try:
                class_package = class_path.split(':')[0]
                class_name = class_path.split(':')[1]
                parser = getattr(importlib.import_module(class_package), class_name)
                # Parse the result using the parser set in the configuration
                result = parser().parse_notification()
            except Exception as e:
                result = {'errors': [type(e).__name__ + ': ' + str(e)]}
        else:
            result = {'errors': ['%s not configured' % PARSER_CONFIG_PROP]}

        # Introduce the users into the datasets
        # Expected result: {'errors': ["...", "...", ...]
        #                   'users_datasets': [{'user': 'user_name', 'datasets': ['ds1', 'ds2', ...]}, ...]}
        warns = []

        if 'errors' in result and len(result['errors']) > 0:
            log.warn('Errors arised parsing the request: ' + str(result['errors']))
            response.status_int = 400
            return helpers.json.dumps({'errors': result['errors']})
        elif 'users_datasets' in result:
            for user_info in result['users_datasets']:
                for dataset_id in user_info['datasets']:
                    try:

                        dataset = plugins.toolkit.get_action('package_show')({'ignore_auth': True, constants.CONTEXT_CALLBACK: True}, {'id': dataset_id})

                        # Create the array
                        if constants.ALLOWED_USERS not in dataset:
                            dataset[constants.ALLOWED_USERS] = []

                        # Add the user only if he/she is not in the list
                        if user_info['user'] not in dataset[constants.ALLOWED_USERS]:
                            dataset[constants.ALLOWED_USERS].append(user_info['user'])
                            plugins.toolkit.get_action('package_update')({'ignore_auth': True}, dataset)
                        else:
                            log.warn('The user %s is already allowed to access the %s dataset' % (user_info['user'], dataset_id))

                    except plugins.toolkit.ObjectNotFound:
                        # If a dataset does not exist in the instance, an error message will be returned to the user.
                        # However the process won't stop and the process will continue with the remaining datasets.
                        log.warn('Dataset %s was not found in this instance' % dataset_id)
                        warns.append('Dataset %s was not found in this instance' % dataset_id)
                    except plugins.toolkit.ValidationError as e:
                        # Some datasets does not allow to introduce the list of allowed users since this property is
                        # only valid for private datasets outside an organization. In this case, a wanr will return
                        # but the process will continue
                        warns.append('Dataset %s: %s' % (dataset_id, e.error_dict[constants.ALLOWED_USERS][0]))

        # Commit the changes
        model.Session.commit()

        # Return warnings that inform about non-existing datasets
        if len(warns) > 0:
            return helpers.json.dumps({'warns': warns})
