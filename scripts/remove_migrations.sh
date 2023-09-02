# Change the working directory
cd "$(dirname -- "${BASH_SOURCE[0]}")/.."

# Declare an array of directories
declare -a dirs=('generic' 'app' 'Appointment' 'yplibrary' 
                 'questionnaire' 'dormitory' 'record' 'feedback' 'achievement' 'semester')

# Loop over each directory and remove its migrations
for dir in "${dirs[@]}"; do
    rm -rf "${dir}/migrations/*"
    echo "Remove migrations in ${dir}/migrations/*"
done
