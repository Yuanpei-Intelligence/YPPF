cd $( dirname -- "${BASH_SOURCE[0]}" )/..
for i in 'app' 'Appointment' 'generic' 'yp_library' 'questionnaire' 'dormitory' 'feedback' 'achievement'
do
    rm -rf $i/migrations/*
done
