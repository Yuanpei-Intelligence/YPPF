"""
App scheduler provides other apps a way to add job to database.

There shouldn't be multiple schedulers that can execute the job, otherwise a job
could be executed multiple times. App scheduler provide a command 
`python3 manage.py runscheduler` to start the job executor, which will
actually run the job in a stand alone process.
"""