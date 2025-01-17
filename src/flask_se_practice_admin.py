"""
   Copyright 2023 Alexander Slugin

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
"""
# -*- coding: utf-8 -*-

from enum import Enum
from functools import wraps
import shutil
import tempfile

from flask import flash, redirect, request, render_template, url_for, send_file, session
from flask_login import current_user
from zipfile import ZipFile
from transliterate import translit

from flask_se_auth import login_required
from se_forms import ChooseCourseAndYear
from se_models import (
    AreasOfStudy,
    CurrentThesis,
    Worktype,
    NotificationPractice,
    db,
    add_mail_notification,
    Staff,
    Courses,
    Thesis,
)

from flask_se_config import get_thesis_type_id_string
from templates.practice.admin.templates import PracticeAdminTemplates
from templates.notification.templates import NotificationTemplates
from flask_se_practice_yandex_disk import handle_yandex_table
from flask_se_practice_config import (
    TABLE_COLUMNS,
    TEXT_UPLOAD_FOLDER,
    PRESENTATION_UPLOAD_FOLDER,
    REVIEW_UPLOAD_FOLDER,
    ARCHIVE_TEXT_FOLDER,
    ARCHIVE_REVIEW_FOLDER,
    ARCHIVE_PRESENTATION_FOLDER,
    get_filename,
    TypeOfFile,
)
from flask_se_practice_table import edit_table


class PracticeAdminPage(Enum):
    CURRENT_THESISES = "current_thesises"
    FINISHED_THESISES = "finished_thesises"
    THESIS = "thesis"


request_column_names = {
    "name": "user_name_column",
    "how_to_contact": "how_to_contact_column",
    "supervisor": "supervisor_column",
    "consultant": "consultant_column",
    "theme": "theme_column",
    "text": "text_column",
    "supervisor_review": "supervisor_review_column",
    "reviewer_review": "reviewer_review_column",
    "code": "code_column",
    "committer": "committer_column",
    "presentation": "presentation_column",
}


def __get_filename_without_extension(worktype: Worktype, area: AreasOfStudy) -> str:
    if worktype is None or area is None:
        return ""
    return (
        get_thesis_type_id_string(worktype.id)
        + "_"
        + translit(area.area, "ru", reversed=True).replace(" ", "_")
    )


def user_is_staff(func):
    @wraps(func)
    def check_user_is_staff_decorator(*args, **kwargs):
        user_staff = Staff.query.filter_by(user_id=current_user.id).first()
        if not user_staff:
            return redirect(url_for("practice_index"))
        return func(*args, **kwargs)

    return check_user_is_staff_decorator


@login_required
@user_is_staff
def choose_area_and_worktype_admin():
    area_id = request.args.get("area_id", type=int)
    worktype_id = request.args.get("worktype_id", type=int)

    previous_page = session.get("previous_page")
    if previous_page == PracticeAdminPage.CURRENT_THESISES.value:
        return redirect(
            url_for("index_admin", area_id=area_id, worktype_id=worktype_id)
        )
    elif previous_page == PracticeAdminPage.FINISHED_THESISES.value:
        return redirect(
            url_for("finished_thesises_admin", area_id=area_id, worktype_id=worktype_id)
        )

    return redirect(url_for("index_admin", area_id=area_id, worktype_id=worktype_id))


@login_required
@user_is_staff
def index_admin():
    area_id = request.args.get("area_id", type=int)
    worktype_id = request.args.get("worktype_id", type=int)
    area = AreasOfStudy.query.filter_by(id=area_id).first()
    worktype = Worktype.query.filter_by(id=worktype_id).first()

    if request.method == "POST":
        if "download_materials_button" in request.form:
            return download_materials(area, worktype)
        if "finish_all_work_button" in request.form:
            thesises = (
                CurrentThesis.query.filter_by(area_id=area_id)
                .filter_by(worktype_id=worktype_id)
                .filter_by(deleted=False)
                .filter_by(status=1)
                .filter(CurrentThesis.title != None)
                .all()
            )
            for thesis in thesises:
                thesis.status = 2
            db.session.commit()

        if "download_table" in request.form:
            filename = __get_filename_without_extension(worktype, area) + ".xlsx"
            with tempfile.TemporaryDirectory() as tmp:
                full_filename = tmp + "/" + filename
                edit_table(
                    path_to_table=full_filename,
                    area_id=area.id,
                    worktype_id=worktype.id,
                )
                return send_file(
                    full_filename, download_name=filename, as_attachment=True
                )

        if "yandex_button" in request.form:
            try:
                table_name = request.form["table_name"]
                sheet_name = request.form["sheet_name"]
                if table_name is None or table_name == "":
                    flash(
                        "Введите название файла для выгрузки на Яндекс Диск",
                        category="error",
                    )
                    return redirect(
                        url_for("index_admin", area_id=area.id, worktype_id=worktype.id)
                    )

                if table_name.split(".")[-1] != "xlsx":
                    flash(
                        "Файл таблицы должен быть с расширением .xlsx", category="error"
                    )
                    return redirect(
                        url_for("index_admin", area_id=area.id, worktype_id=worktype.id)
                    )

                column_names = []
                for column in TABLE_COLUMNS:
                    column_value = request.form.get(request_column_names[column], "")
                    if not column_value or column_value == "":
                        flash(
                            "Название столбца таблицы не может быть пустым",
                            category="error",
                        )
                        return redirect(
                            url_for(
                                "index_admin", area_id=area.id, worktype_id=worktype.id
                            )
                        )
                    column_names.append((column, column_value))

                return handle_yandex_table(
                    table_name=table_name,
                    sheet_name=sheet_name,
                    area_id=area.id,
                    worktype_id=worktype.id,
                    column_names_list=column_names,
                )
            except:
                flash(
                    "Что-то пошло не так, измените параметры и попробуйте заново",
                    category="error",
                )
                return redirect(
                    url_for("index_admin", area_id=area.id, worktype_id=worktype.id)
                )

    list_of_areas = (
        AreasOfStudy.query.filter(AreasOfStudy.id > 1).order_by(AreasOfStudy.id).all()
    )
    list_of_work_types = Worktype.query.filter(Worktype.id > 2).all()
    list_of_thesises = (
        CurrentThesis.query.filter_by(area_id=area_id)
        .filter_by(worktype_id=worktype_id)
        .filter_by(deleted=False)
        .filter_by(status=1)
        .filter(CurrentThesis.title != None)
        .all()
    )
    table_name = __get_filename_without_extension(worktype, area) + ".xlsx"
    session["previous_page"] = PracticeAdminPage.CURRENT_THESISES.value

    return render_template(
        PracticeAdminTemplates.CURRENT_THESISES.value,
        area=area,
        worktype=worktype,
        list_of_areas=list_of_areas,
        list_of_worktypes=list_of_work_types,
        list_of_thesises=list_of_thesises,
        table_columns=TABLE_COLUMNS,
        default_table_name=table_name,
    )


@login_required
@user_is_staff
def download_materials(area, worktype):
    thesises = (
        CurrentThesis.query.filter_by(area_id=area.id)
        .filter_by(worktype_id=worktype.id)
        .filter_by(deleted=False)
        .filter_by(status=1)
        .all()
    )

    filename = __get_filename_without_extension(worktype, area) + ".zip"
    with tempfile.NamedTemporaryFile() as tmp:
        with ZipFile(tmp.name, "w") as zip_file:
            for thesis in thesises:
                if thesis.text_uri is not None:
                    zip_file.write(
                        TEXT_UPLOAD_FOLDER + thesis.text_uri, arcname=thesis.text_uri
                    )
                if thesis.supervisor_review_uri is not None:
                    zip_file.write(
                        REVIEW_UPLOAD_FOLDER + thesis.supervisor_review_uri,
                        arcname=thesis.supervisor_review_uri,
                    )
                if thesis.reviewer_review_uri is not None:
                    zip_file.write(
                        REVIEW_UPLOAD_FOLDER + thesis.reviewer_review_uri,
                        arcname=thesis.reviewer_review_uri,
                    )
                if thesis.presentation_uri is not None:
                    zip_file.write(
                        PRESENTATION_UPLOAD_FOLDER + thesis.presentation_uri,
                        arcname=thesis.presentation_uri,
                    )

        return send_file(tmp.name, download_name=filename, as_attachment=True)


@login_required
@user_is_staff
def thesis_admin():
    current_thesis_id = request.args.get("id", type=int)
    if not current_thesis_id:
        return redirect(url_for("index_admin"))

    current_thesis = CurrentThesis.query.filter_by(id=current_thesis_id).first()
    if not current_thesis:
        return redirect(url_for("index_admin"))

    if request.method == "POST":
        if "submit_notification_button" in request.form:
            if request.form["content"] in {None, ""}:
                flash("Нельзя отправить пустое уведомление!", category="error")
                return redirect(url_for("thesis_staff", id=current_thesis.id))

            mail_notification = render_template(
                NotificationTemplates.NOTIFICATION_FROM_CURATOR.value,
                curator=current_user,
                thesis=current_thesis,
                content=request.form["content"],
            )
            add_mail_notification(
                current_thesis.author_id,
                "[SE site] Уведомление от руководителя практики",
                mail_notification,
            )

            notification_content = (
                f"Руководитель практики {current_user.get_name()} "
                f'отправил Вам уведомление по работе "{current_thesis.title}": '
                f"{request.form['content']}"
            )
            notification = NotificationPractice(
                recipient_id=current_thesis.author_id, content=notification_content
            )
            db.session.add(notification)
            db.session.commit()
            flash("Уведомление отправлено!", category="success")
        elif "submit_edit_title_button" in request.form:
            new_title = request.form["title_input"]
            notification_content = (
                "Руководитель практики изменил название Вашей работы "
                + f'"{current_thesis.title}" на "{new_title}"'
            )
            current_thesis.title = new_title
            add_mail_notification(
                current_thesis.author_id,
                "[SE site] Уведомление от руководителя практики",
                notification_content,
            )
            notification = NotificationPractice(
                recipient_id=current_thesis.author_id, content=notification_content
            )
            db.session.add(notification)
            db.session.commit()
        elif "submit_finish_work_button" in request.form:
            current_thesis.status = 2
            db.session.commit()
        elif "submit_restore_work_button" in request.form:
            current_thesis.status = 1
            db.session.commit()

    list_of_areas = (
        AreasOfStudy.query.filter(AreasOfStudy.id > 1).order_by(AreasOfStudy.id).all()
    )
    list_of_work_types = Worktype.query.filter(Worktype.id > 2).all()
    not_deleted_tasks = [task for task in current_thesis.tasks if not task.deleted]
    session["previous_page"] = PracticeAdminPage.THESIS.value
    return render_template(
        PracticeAdminTemplates.THESIS.value,
        area=current_thesis.area,
        worktype=current_thesis.worktype,
        list_of_areas=list_of_areas,
        list_of_worktypes=list_of_work_types,
        thesis=current_thesis,
        tasks=not_deleted_tasks,
    )


@login_required
@user_is_staff
def archive_thesis():
    current_thesis_id = request.args.get("id", type=int)
    if not current_thesis_id:
        return redirect(url_for("index_admin"))

    current_thesis: CurrentThesis = CurrentThesis.query.filter_by(
        id=current_thesis_id
    ).first()
    if not current_thesis:
        return redirect(url_for("index_admin"))

    if request.method == "POST":
        if "thesis_to_archive_button" in request.form:
            course_id = request.form.get("course", type=int)
            if course_id == 0:
                flash(
                    "Выберите направление обучения (бакалавриат/магистратура)",
                    category="error",
                )
                return redirect(url_for("archive_thesis", id=current_thesis.id))

            text_file = request.files["text"] if "text" in request.files else None
            if not current_thesis.text_uri and not text_file:
                flash(
                    "Загрузите текст работы, чтобы перенести её в архив",
                    category="error",
                )
                return redirect(url_for("archive_thesis", id=current_thesis.id))

            presentation_file = (
                request.files["presentation"]
                if "presentation" in request.files
                else None
            )
            if not current_thesis.presentation_uri and not presentation_file:
                flash(
                    "Загрузите презентацию работы, чтобы перенести её в архив",
                    category="error",
                )
                return redirect(url_for("archive_thesis", id=current_thesis.id))

            supervisor_review_file = (
                request.files["supervisor_review"]
                if "supervisor_review" in request.files
                else None
            )
            if not current_thesis.supervisor_review_uri and not supervisor_review_file:
                flash(
                    "Загрузите отзыв научного руководителя, чтобы перенести работу в архив",
                    category="error",
                )
                return redirect(url_for("archive_thesis", id=current_thesis.id))

            thesis = Thesis()
            thesis.type_id = current_thesis.worktype_id
            thesis.course_id = course_id
            thesis.area_id = current_thesis.area_id
            thesis.name_ru = current_thesis.title
            thesis.author = current_thesis.user.get_name()
            thesis.author_id = current_thesis.author_id
            thesis.supervisor_id = current_thesis.supervisor_id
            thesis.publish_year = request.form.get("publish_year", type=int)

            path_to_archive_text, archive_text_filename = get_filename(
                current_thesis, ARCHIVE_TEXT_FOLDER, TypeOfFile.TEXT.value
            )
            if current_thesis.text_uri:
                shutil.copyfile(
                    TEXT_UPLOAD_FOLDER + current_thesis.text_uri, path_to_archive_text
                )
            else:
                text_file.save(path_to_archive_text)
            thesis.text_uri = archive_text_filename

            path_to_archive_presentation, archive_slides_filename = get_filename(
                current_thesis,
                ARCHIVE_PRESENTATION_FOLDER,
                TypeOfFile.PRESENTATION.value,
            )
            if current_thesis.presentation_uri:
                shutil.copyfile(
                    PRESENTATION_UPLOAD_FOLDER + current_thesis.presentation_uri,
                    path_to_archive_presentation,
                )
            else:
                presentation_file.save(path_to_archive_presentation)
            thesis.presentation_uri = archive_slides_filename

            path_to_archive_super_review, archive_super_review_filename = get_filename(
                current_thesis,
                ARCHIVE_REVIEW_FOLDER,
                TypeOfFile.SUPERVISOR_REVIEW.value,
            )
            if current_thesis.supervisor_review_uri:
                shutil.copyfile(
                    REVIEW_UPLOAD_FOLDER + current_thesis.supervisor_review_uri,
                    path_to_archive_super_review,
                )
            else:
                supervisor_review_file.save(path_to_archive_super_review)
            thesis.supervisor_review_uri = archive_super_review_filename

            path_to_archive_rev_review, archive_rev_review_filename = get_filename(
                current_thesis, ARCHIVE_REVIEW_FOLDER, TypeOfFile.REVIEWER_REVIEW.value
            )
            if current_thesis.reviewer_review_uri:
                shutil.copyfile(
                    REVIEW_UPLOAD_FOLDER + current_thesis.reviewer_review_uri,
                    path_to_archive_rev_review,
                )
            else:
                reviewer_review_file = (
                    request.files["consultant_review"]
                    if "consultant_review" in request.files
                    else None
                )
                if reviewer_review_file not in {None, ""}:
                    reviewer_review_file.save(path_to_archive_rev_review)
                    thesis.reviewer_review_uri = archive_rev_review_filename

            if current_thesis.code_link and current_thesis.code_link.find("http") != -1:
                thesis.source_uri = current_thesis.code_link
            else:
                code_link = request.form.get("code_link", type=str)
                if code_link not in {None, ""} and code_link.find("http") != -1:
                    thesis.source_uri = code_link

            db.session.add(thesis)
            current_thesis.archived = True
            current_thesis.status = 2

            add_mail_notification(
                current_thesis.author_id,
                "[SE site] Ваша работа перенесена в архив практик и ВКР",
                render_template(
                    NotificationTemplates.THESIS_WAS_ARCHIVED_BY_ADMIN.value,
                    curator=current_user,
                    thesis=current_thesis,
                ),
            )
            notification_content = (
                f"Руководитель практики { current_user.get_name() }"
                f' перенёс Вашу работу "{ current_thesis.title }"'
                f" в архив практик и ВКР."
            )
            notification = NotificationPractice(
                recipient_id=current_thesis.author_id, content=notification_content
            )
            db.session.add(notification)
            db.session.commit()
            flash("Работа перенесена в архив!", category="success")
            return redirect(url_for("thesis_admin", id=current_thesis.id))

    list_of_areas = (
        AreasOfStudy.query.filter(AreasOfStudy.id > 1).order_by(AreasOfStudy.id).all()
    )
    list_of_work_types = Worktype.query.filter(Worktype.id > 2).all()
    course_and_year_form = ChooseCourseAndYear()
    course_and_year_form.course.choices.append((0, "Выберите направление"))
    for course in Courses.query.all():
        course_and_year_form.course.choices.append((course.id, course.name))

    return render_template(
        PracticeAdminTemplates.ARCHIVE_THESIS.value,
        thesis=current_thesis,
        area=current_thesis.area,
        worktype=current_thesis.worktype,
        list_of_areas=list_of_areas,
        list_of_worktypes=list_of_work_types,
        form=course_and_year_form,
    )


@login_required
@user_is_staff
def finished_thesises_admin():
    area_id = request.args.get("area_id", type=int)
    worktype_id = request.args.get("worktype_id", type=int)
    area = AreasOfStudy.query.filter_by(id=area_id).first()
    worktype = Worktype.query.filter_by(id=worktype_id).first()

    current_thesises = (
        CurrentThesis.query.filter_by(area_id=area_id)
        .filter_by(worktype_id=worktype_id)
        .filter_by(status=2)
        .filter_by(deleted=False)
        .filter(CurrentThesis.title != None)
        .all()
    )

    list_of_areas = (
        AreasOfStudy.query.filter(AreasOfStudy.id > 1).order_by(AreasOfStudy.id).all()
    )
    list_of_work_types = Worktype.query.filter(Worktype.id > 2).all()
    session["previous_page"] = PracticeAdminPage.FINISHED_THESISES.value
    return render_template(
        PracticeAdminTemplates.FINISHED_THESISES.value,
        area=area,
        worktype=worktype,
        list_of_areas=list_of_areas,
        list_of_worktypes=list_of_work_types,
        thesises=current_thesises,
    )
