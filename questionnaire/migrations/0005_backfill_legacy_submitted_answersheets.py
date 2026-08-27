from django.db import migrations


DRAFT = 0
SUBMITTED = 1
BATCH_SIZE = 1000
LEGACY_DORMITORY_TITLE_PREFIX = '宿舍生活习惯调研-'
LEGACY_DORMITORY_DESCRIPTION = '根据问卷情况对宿舍进行分配'


def _is_legacy_dormitory_survey(title, description):
    """Return whether persisted survey metadata identifies the legacy flow."""
    if description != LEGACY_DORMITORY_DESCRIPTION:
        return False
    if not title.startswith(LEGACY_DORMITORY_TITLE_PREFIX):
        return False
    year = title[len(LEGACY_DORMITORY_TITLE_PREFIX):]
    return len(year) == 4 and year.isdigit()


def backfill_legacy_submitted_answersheets(apps, schema_editor):
    """Mark complete legacy sheets submitted without promoting real drafts.

    The legacy dormitory form used surveys created with a repository-defined
    title and description, wrote at least one AnswerText row, and wrote a row
    for every required question before rendering the response as submitted.
    Both the flow-specific survey metadata and answer coverage are required;
    completed drafts for ordinary surveys must remain drafts.
    """
    AnswerSheet = apps.get_model('questionnaire', 'AnswerSheet')
    AnswerText = apps.get_model('questionnaire', 'AnswerText')
    Question = apps.get_model('questionnaire', 'Question')
    Survey = apps.get_model('questionnaire', 'Survey')
    database = schema_editor.connection.alias
    legacy_survey_ids = {
        survey_id
        for survey_id, title, description in (
            Survey.objects.using(database)
            .filter(
                title__startswith=LEGACY_DORMITORY_TITLE_PREFIX,
                description=LEGACY_DORMITORY_DESCRIPTION,
            )
            .values_list('pk', 'title', 'description')
        )
        if _is_legacy_dormitory_survey(title, description)
    }
    if not legacy_survey_ids:
        return
    last_sheet_id = 0

    while True:
        sheets = list(
            AnswerSheet.objects.using(database)
            .filter(
                status=DRAFT,
                pk__gt=last_sheet_id,
                survey_id__in=legacy_survey_ids,
            )
            .order_by('pk')
            .values_list('pk', 'survey_id')[:BATCH_SIZE]
        )
        if not sheets:
            break
        last_sheet_id = sheets[-1][0]
        sheet_ids = [sheet_id for sheet_id, _ in sheets]
        survey_ids = {survey_id for _, survey_id in sheets}

        required_questions = {survey_id: set() for survey_id in survey_ids}
        for question_id, survey_id in (
            Question.objects.using(database)
            .filter(survey_id__in=survey_ids, required=True)
            .values_list('pk', 'survey_id')
        ):
            required_questions[survey_id].add(question_id)

        answered_questions = {sheet_id: set() for sheet_id in sheet_ids}
        for sheet_id, question_id in (
            AnswerText.objects.using(database)
            .filter(answersheet_id__in=sheet_ids)
            .values_list('answersheet_id', 'question_id')
        ):
            answered_questions[sheet_id].add(question_id)

        completed_sheet_ids = [
            sheet_id
            for sheet_id, survey_id in sheets
            if answered_questions[sheet_id]
            and required_questions[survey_id].issubset(
                answered_questions[sheet_id]
            )
        ]
        if completed_sheet_ids:
            AnswerSheet.objects.using(database).filter(
                pk__in=completed_sheet_ids,
                status=DRAFT,
            ).update(status=SUBMITTED)


class Migration(migrations.Migration):

    dependencies = [
        ('questionnaire', '0004_answersheet_unique_creator_survey'),
    ]

    operations = [
        migrations.RunPython(
            backfill_legacy_submitted_answersheets,
            # Backfilled rows cannot later be distinguished from submissions
            # created normally, so reversing must not reopen either group.
            reverse_code=migrations.RunPython.noop,
        ),
    ]
