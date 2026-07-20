pipeline {

    agent any


    environment {

        REGISTRY = 'ghcr.io'
        OWNER = 'rohitkumar7299'
        GHCR = credentials('ghcr-creds')
        EC2_IP = '40.192.16.213'

    }


    stages {


        stage('Checkout') {
            steps {
                checkout scm
            }
        }


        stage('Lint') {

            steps {

                sh '''
                    python3 -m pip install --break-system-packages ruff==0.15.21

                    python3 -m ruff check \
                    services/payment-svc/app \
                    services/mandate-svc/app \
                    services/ledger-svc/app \
                    services/settlement-worker/worker.py
                '''

            }

        }



        stage('Login to GHCR') {

            steps {

                sh '''
                    echo "$GHCR_PSW" | docker login ghcr.io \
                    -u "$GHCR_USR" \
                    --password-stdin
                '''

            }

        }



        stage('Build and Push Images') {

            steps {

                script {


                    def services = [
                        'payment-svc',
                        'mandate-svc',
                        'ledger-svc',
                        'settlement-worker',
                        'portal'
                    ]


                    services.each { svc ->


                        def image = "${REGISTRY}/${OWNER}/paylane-${svc}"


                        sh """

                            echo "Building ${image}"


                            docker build -t ${image}:${BUILD_NUMBER} -t ${image}:latest services/${svc}


                            echo "Pushing ${image}:${BUILD_NUMBER}"

                            docker push ${image}:${BUILD_NUMBER}

                            docker push ${image}:latest

                        """

                    }

                }

            }

        }




        stage('Deploy to EC2') {


            steps {


                sshagent(['paylane-ec2-key']) {


                    sh '''

                    ssh -o StrictHostKeyChecking=no ubuntu@${EC2_IP} "

                    cd /opt/paylane &&


                    echo '$GHCR_PSW' | docker login ghcr.io \
                    -u '$GHCR_USR' \
                    --password-stdin &&


                    docker compose -f docker-compose.yml pull &&


                    docker compose -f docker-compose.yml up -d

                    "

                    '''

                }

            }

        }




        stage('Verify Deployment') {


            steps {


                sshagent(['paylane-ec2-key']) {


                    sh '''

                    ssh -o StrictHostKeyChecking=no ubuntu@${EC2_IP} "

                    cd /opt/paylane &&

                    docker ps

                    "

                    '''

                }

            }

        }


    }



    post {


        success {

            echo "Paylane deployment successful"

        }


        failure {

            echo "Paylane deployment failed"

        }


        always {

            sh '''

            docker logout ghcr.io || true

            '''

        }

    }

}
