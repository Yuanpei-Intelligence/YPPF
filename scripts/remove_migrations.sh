cd $( dirname -- "${BASH_SOURCE[0]}" )/..
for i in 'app' 'Appointment' 'generic' 'yplibrary'
do
    rm -rf $i/migrations/*
done
