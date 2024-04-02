from crypt import methods
import os
import flask
import secrets
import string
from sqlalchemy import *
from sqlalchemy.pool import NullPool
from flask import Flask, flash, request, render_template, g, redirect, Response, url_for
import flask_login
from flask_login import UserMixin, login_user, current_user
from itertools import groupby
from operator import itemgetter

tmpl_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
app = Flask(__name__, template_folder=tmpl_dir)

# Flask login manager
login_manager = flask_login.LoginManager()
login_manager.init_app(app)
# Each flask-login session requires long random alphanumeric key to sign the session cookie
app.secret_key = os.urandom(24)


# ADD DATABASE CREDENTIALS HERE BEFORE RUNNING; DO NOT PUSH
DATABASE_USERNAME = "vb2589"
DATABASE_PASSWRD = "18091303"
DATABASE_HOST = "35.212.75.104"
DATABASEURI = f"postgresql://{DATABASE_USERNAME}:{DATABASE_PASSWRD}@{DATABASE_HOST}/proj1part2"

# Create database engine
engine = create_engine(DATABASEURI)  # noqa: F405

# Example query in database
with engine.connect() as conn:
    create_table_command = """
    CREATE TABLE IF NOT EXISTS test (
        id serial,
        name text
    )
    """
    res = conn.execute(text(create_table_command))
    insert_table_command = """INSERT INTO test(name) VALUES ('grace hopper'), ('alan turing'), ('ada lovelace')"""
    res = conn.execute(text(insert_table_command))
    # you need to commit for create, insert, update queries to reflect
    conn.commit()

@app.before_request
def before_request():
    """
    This function is run at the beginning of every web request
    (every time you enter an address in the web browser).
    We use it to setup a database connection that can be used throughout the request.

    The variable g is globally accessible.
    """
    try:
        g.conn = engine.connect()
    except:
        print("uh oh, problem connecting to database")
        import traceback; traceback.print_exc()
        g.conn = None

@app.teardown_request
def teardown_request(exception):
    """
    At the end of the web request, this makes sure to close the database connection.
    If you don't, the database could run out of memory!
    """
    try:
        g.conn.close()
    except Exception as e:
        pass


@app.route('/')
def index():
    """
    request is a special object that Flask provides to access web request information:

    request.method:   "GET" or "POST"
    request.form:     if the browser submitted a form, this contains the data in the form
    request.args:     dictionary of URL arguments, e.g., {a:1, b:2} for http://localhost?a=1&b=2

    See its API: https://flask.palletsprojects.com/en/1.1.x/api/#incoming-request-data
    """
    if not current_user.is_authenticated:
        return redirect(url_for('login'))

    username = current_user.username

    candidate_check_query = """SELECT EXISTS(SELECT 1 FROM Candidate WHERE Username = :username)"""
    is_candidate = g.conn.execute(text(candidate_check_query), {'username': username}).scalar()

    recruiter_check_query = """SELECT EXISTS(SELECT 1 FROM Recruiter WHERE Username = :username)"""
    is_recruiter = g.conn.execute(text(recruiter_check_query), {'username': username}).scalar()

    if is_candidate:
        return render_template('index_candidates.html')
    elif is_recruiter:
        return render_template('index_recruiters.html')
    else:
        return "Unauthorized access", 401


###########################################
# User authentication
###########################################
class User(UserMixin):
    def __init__(self, username):
        self.username = username

    def get_id(self):
        return self.username


@login_manager.user_loader
def user_loader(username):
    user = User(username)
    return user


@login_manager.request_loader
def request_loader(request):
    username = request.form.get('username')
    if username:
        user = User(username)
        user.id = username
        return user
    return None


@login_manager.unauthorized_handler
def unauthorized_handler():
    return 'Unauthorized', 401

def generate_random_string(length=36):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if flask.request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        candidate_usernames_query = """SELECT DISTINCT Username FROM Candidate"""
        candidate_usernames = [row[0] for row in g.conn.execute(text(candidate_usernames_query))]

        recruiter_usernames_query = """SELECT DISTINCT Username FROM Recruiter"""
        recruiter_usernames = [row[0] for row in g.conn.execute(text(recruiter_usernames_query))]

        # If candidate, redirect to candidate view
        if username in candidate_usernames:
            user = User(username)

            # Assume password is same as username
            if password == username:
                login_user(user)
                return redirect(url_for('index'))
            else:
                return 'Invalid username or password'

        # If recruiter, redirect to recruiter view
        if username in recruiter_usernames:
            user = User(username)
            if password == username:
                login_user(user)
                return redirect(url_for('index'))
            else:
                return 'Invalid username or password'

    return render_template('login.html')


@app.route('/logout')
def logout():
    pass


@app.route('/job_board', methods=('GET','POST'))
def job_board():
    # Only allow candidates to apply to jobs: check if candidate user
    is_candidate = False
    if current_user.is_authenticated:
        candidate_check_query = """SELECT EXISTS(SELECT 1 FROM Candidate WHERE Username = :username)"""
        is_candidate = g.conn.execute(text(candidate_check_query), {'username': current_user.username}).scalar()
    else:
        return redirect(url_for('login'))

    # Default query (i.e. what is executed if user does not select anything specific to filter by)
    base_search_query = """SELECT j.Job_ID, j.Job_Title, j.Experience, j.Location, j.Requirements, j.Skills, 
                               c.Name as Company_Name, r.Username as Recruiter_Username, r.Name as Recruiter_Name
                               FROM Job_Posting j
                               JOIN Company c ON j.Company_ID = c.Company_ID
                               JOIN Recruiter r ON j.Recruiter_Username = r.Username
    """
    if request.method == "POST":

        # Collect all user selected field values
        location = request.form.get('Location', '')
        company = request.form.get('Company', '')
        skills = request.form.get('Skills', '')
        search = request.form.get('Search', '')
        experience = request.form.get('Experience', '')
        role_types = request.form.getlist('role_types')

        # Keep track of all user selected fields to filter by to build SQL query
        where_clauses = []
        params = {}

        # Collect user selected field values
        if location:
            where_clauses.append("j.location LIKE :location")
            params['location'] = "%" + location + "%"

        if company:
            where_clauses.append("c.Name LIKE :company")
            params['company'] = "%" + company + "%"

        if skills:
            where_clauses.append("j.Skills LIKE :skills")
            params['skills'] = "%" + skills + "%"

        if experience:
            where_clauses.append("j.Experience LIKE :experience")
            params['experience'] = "%" + experience + "%"

        if role_types:
            # Depending on the role type selected, need to select jobs from the corresponding table
            role_queries = []
            if 'full_time' in role_types:
                role_queries.append("j.Job_ID IN (SELECT Job_ID FROM Full_Time_Job)")
            if 'internship' in role_types:
                role_queries.append("j.Job_ID IN (SELECT Job_ID FROM Internship_Job)")
            if 'coop' in role_types:
                role_queries.append("j.Job_ID IN (SELECT Job_ID FROM Co_Op_Job)")
            where_clauses.append("(" + " OR ".join(role_queries) + ")")

        if search:
            # If user is searching, set up filter query statements based on the keywords they entered
            search_clauses = " OR ".join([
                "j.location LIKE :search",
                "c.Name LIKE :search",
                "j.Skills LIKE :search",
                "j.Job_Title LIKE :search",
                "j.Experience LIKE :search",
                "j.Requirements LIKE :search",
                "r.Name LIKE :search"
            ])
            where_clauses.append(f"({search_clauses})")
            params["search"] = "%" + search + "%"

        # Check which query to execute: query with user selected params if any, and if not any then default to show all
        if where_clauses:
            full_query = base_search_query + " WHERE " + " AND ".join(where_clauses)
        else:
            full_query = base_search_query

        # Execute query
        cursor = g.conn.execute(text(full_query), params)
        postings = cursor.fetchall()
        cursor.close()

        return render_template('job_board.html', postings=postings, is_candidate=is_candidate)

    # if no filter is applied, show all postings
    cursor = g.conn.execute(text(base_search_query))
    postings = cursor.fetchall()
    cursor.close()

    return render_template('job_board.html', postings=postings, is_candidate=is_candidate)


@app.route('/apply', methods=['POST'])
def apply_for_job():
    application_id = generate_random_string()
    job_id = request.form['job_id']
    candidate_username = current_user.username
    recruiter_username = request.form['recruiter_username']
    resume = request.form['resume']
    cover_letter = request.form['cover_letter']
    status = 'Active'

    # Add job application into Application table
    insert_query = """INSERT INTO Application (Application_ID, Job_ID, Candidate_Username, Recruiter_Username, 
                      Resume, Cover_Letter, Status)
                      VALUES (:application_id, :job_id, :candidate_username, :recruiter_username, :resume, 
                      :cover_letter, :status)
                   """

    g.conn.execute(text(insert_query), {
        'application_id': application_id,
        'job_id': job_id,
        'candidate_username': candidate_username,
        'recruiter_username': recruiter_username,
        'resume': resume,
        'cover_letter': cover_letter,
        'status': status
    })
    # Need this to ensure transaction updates table
    g.conn.commit()

    return redirect(url_for('job_board'))

@app.route('/post_job', methods=['GET', 'POST'])
def post_job():
    if not current_user.is_authenticated:
        return redirect(url_for('login'))

    # Check if the current user is a recruiter
    recruiter_check_query = """SELECT EXISTS(SELECT 1 FROM Recruiter WHERE Username = :username)"""
    is_recruiter = g.conn.execute(text(recruiter_check_query), {'username': current_user.username}).scalar()
    if not is_recruiter:
        return "Unauthorized access", 401

    # Automatically populate job ID, company ID, and recruiter username
    job_id = generate_random_string()
    company_id_query = "SELECT Company_ID FROM Recruiter WHERE Username = :username"
    company_id_result = g.conn.execute(text(company_id_query), {'username': current_user.username}).fetchone()
    company_id = company_id_result[0]
    recruiter_username = current_user.username

    if request.method == 'POST':
        # Collect form data
        job_title = request.form['Job_Title']
        experience = request.form['Experience']
        location = request.form['Location']
        requirements = request.form['Requirements']
        skills = request.form['Skills']
        job_type = request.form['job_type']

        # Look up the portal_id for the company
        portal_query = """SELECT Portal_ID FROM Job_Portal WHERE Company_ID = :company_id"""
        portal_result = g.conn.execute(text(portal_query), {'company_id': company_id}).fetchone()
        portal_id = portal_result[0]

        # Add new role as row in Job_Posting table
        insert_query = """INSERT INTO Job_Posting (Job_ID, Job_Title, Experience, Location, Requirements, Skills, 
                          Company_ID, Recruiter_Username, Portal_ID)
                          VALUES (:job_id, :job_title, :experience, :location, :requirements, :skills, :company_id, 
                          :recruiter_username, :portal_id)"""
        g.conn.execute(text(insert_query), {
            'job_id': job_id,
            'job_title': job_title,
            'experience': experience,
            'location': location,
            'requirements': requirements,
            'skills': skills,
            'company_id': company_id,
            'recruiter_username': recruiter_username,
            'portal_id': portal_id
        })
        g.conn.commit()

        # Add other table-specific information depending on the job type
        if job_type == 'full_time':
            annual_salary = request.form['AnnualSalary']
            insert_query = "INSERT INTO Full_Time_Job (Job_ID, AnnualSalary) VALUES (:job_id, :annual_salary)"
            g.conn.execute(text(insert_query), {
                'job_id': job_id,
                'annual_salary': annual_salary
            })
            g.conn.commit()

        elif job_type == 'internship':
            duration = request.form['Duration']
            salaried = request.form['Salaried'] == 'true'
            insert_query = "INSERT INTO Internship_Job (Job_ID, Duration, Salaried) VALUES (:job_id, :duration, :salaried)"
            g.conn.execute(text(insert_query), {
                'job_id': job_id,
                'duration': duration,
                'salaried': salaried
            })
            g.conn.commit()

        elif job_type == 'coop':
            duration = request.form['Duration']
            salaried = request.form['Salaried'] == 'true'
            coop_type = request.form['Type']
            insert_query = "INSERT INTO Co_Op_Job (Job_ID, Duration, Salaried, Type) VALUES (:job_id, :duration, :salaried, :coop_type)"
            g.conn.execute(text(insert_query), {
                'job_id': job_id,
                'duration': duration,
                'salaried': salaried,
                'coop_type': coop_type
            })
            g.conn.commit()

        return redirect(url_for('job_board'))

    return render_template('post_job.html', job_id=job_id, company_id=company_id, recruiter_username=recruiter_username)

@app.route('/post_review',methods=['GET','POST'])
def post_review():
    if not current_user.is_authenticated:
        return redirect(url_for('login'))

    username = current_user.username
    review_id = generate_random_string()

    if request.method=='POST':
        feedback = request.form['Feedback']

        # Case 1: user is a candidate, so show their applications only
        candidate_check_query = """SELECT EXISTS(SELECT 1 FROM Candidate WHERE Username = :username)"""
        is_candidate = g.conn.execute(text(candidate_check_query), {'username': username}).scalar()
        if is_candidate:
            feedback_query = """INSERT INTO Review (Review_ID, Company_Feedback, Candidate_username)
                            VALUES (:review_id, :feedback,:username)"""
            g.conn.execute(text(feedback_query), {
                'review_id': review_id,
                'feedback': feedback,
                'username': username
            })
            g.conn.commit()

            return redirect(url_for('reviews'))

    return render_template('post_review.html')


@app.route('/reviews')
def reviews():
    # Will have two separate tables on the reviews page: one for candidate reviews, one for employee reviews
    interview_reviews_query = """SELECT Review_ID, Interview_Feedback 
                               FROM Review 
                               WHERE Interview_Feedback IS NOT NULL"""
    company_reviews_query = """SELECT Review_ID, Company_Feedback 
                               FROM Review 
                               WHERE Company_Feedback IS NOT NULL"""
    interview_reviews = g.conn.execute(text(interview_reviews_query)).fetchall()
    company_reviews = g.conn.execute(text(company_reviews_query)).fetchall()

    return render_template("reviews.html", interview_reviews=interview_reviews, company_reviews=company_reviews)


@app.route('/applications')
def applications():
    if not current_user.is_authenticated:
        return redirect(url_for('login'))

    username = current_user.username
    applications_data = []

    # Case 1: user is a candidate, so show their applications only
    candidate_check_query = """SELECT EXISTS(SELECT 1 FROM Candidate WHERE Username = :username)"""
    is_candidate = g.conn.execute(text(candidate_check_query), {'username': username}).scalar()

    if is_candidate:
        applications_query = """SELECT a.*, j.Job_Title, c.Name
                                FROM Application AS a 
                                JOIN Job_Posting j ON a.Job_ID = j.Job_ID 
                                JOIN Company c ON j.Company_ID = c.Company_ID
                                WHERE Candidate_Username = :username"""
        applications_data = g.conn.execute(text(applications_query), {'username': username}).fetchall()
        return render_template('applications_candidate.html', applications=applications_data)

    # Case 2: user is a recruiter, so show all applications for job postings for which they are lead recruiter
    recruiter_check_query = """SELECT EXISTS(SELECT 1 FROM Recruiter WHERE Username = :username)"""
    is_recruiter = g.conn.execute(text(recruiter_check_query), {'username': username}).scalar()

    if is_recruiter:
        applications_query = """SELECT a.*, j.Job_Title, j.Location, j.Requirements 
                                    FROM Application AS a
                                    JOIN Job_Posting j ON a.Job_ID = j.Job_ID
                                    WHERE a.Recruiter_Username = :username
                                    ORDER BY a.Job_ID"""
        # Group by Job_ID before passing to template for distinct jobs to each get their own display table
        applications_data = [row._asdict() for row in g.conn.execute(text(applications_query), {'username': username})]
        grouped_applications = {k: list(v) for k, v in groupby(applications_data, key=itemgetter('job_id'))}

        return render_template('applications_recruiter.html', grouped_applications=grouped_applications)

    return "Unauthorized access", 401


@app.route('/employees')
def employees():
    if not current_user.is_authenticated:
        return redirect(url_for('login'))

    employees_query = """SELECT e.*, c.Name as Company_Name
                         FROM Employee e
                         JOIN Company c ON e.Company_ID = c.Company_ID
                      """
    employees_result = g.conn.execute(text(employees_query)).fetchall()

    return render_template("employee_directory.html", employees=employees_result)





if __name__ == "__main__":
    import click

    @click.command()
    @click.option('--debug', is_flag=True)
    @click.option('--threaded', is_flag=True)
    @click.argument('HOST', default='0.0.0.0')
    @click.argument('PORT', default=8111, type=int)
    def run(debug, threaded, host, port):
        HOST, PORT = host, port
        print("running on %s:%d" % (HOST, PORT))
        app.run(host=HOST, port=PORT, debug=debug, threaded=threaded)

run()
