cd $( dirname -- "${BASH_SOURCE[0]}" )/..
for i in 'app' 'Appointment' 'generic' 'yplibrary' 'questionnaire' 'dormitory'
do
    rm -rf $i/migrations/*
done
