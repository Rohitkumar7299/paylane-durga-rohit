provider "aws" {
  region = var.region
}



# Default VPC
data "aws_vpc" "default" {
  default = true
}


# Default Subnets
data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}



# Latest Ubuntu 24.04 LTS
data "aws_ami" "ubuntu" {
  most_recent = true

  owners = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}



# Security Group
resource "aws_security_group" "paylane" {

  name        = "paylane-app-sg"
  description = "Security group for Paylane application"
  vpc_id      = data.aws_vpc.default.id

  ingress {

    description = "SSH"

    from_port = 22
    to_port   = 22
    protocol  = "tcp"

    cidr_blocks = [
      "${var.my_ip}/32"
    ]
  }

  ingress {

    description = "Application"

    from_port = 3000
    to_port   = 3003
    protocol  = "tcp"

    cidr_blocks = [
      "${var.my_ip}/32"
    ]
  }

  egress {

    from_port = 0
    to_port   = 0
    protocol  = "-1"

    cidr_blocks = [
      "0.0.0.0/0"
    ]
  }

  tags = {
    Name = "paylane-app-sg"
  }
}


# EC2 Instance
resource "aws_instance" "paylane" {

  ami           = data.aws_ami.ubuntu.id
  instance_type = var.instance_type

  key_name = var.key_name

  subnet_id = data.aws_subnets.default.ids[0]

  vpc_security_group_ids = [
    aws_security_group.paylane.id
  ]

  associate_public_ip_address = true

  tags = {
    Name = "paylane-app"
  }
}



# Updating the EC2 Pub Ip into Ansible inventory file automatically
resource "local_file" "ansible_inventory" {

  filename = "../ansible/inventory.ini"

  content = <<EOF
[paylane]
${aws_instance.paylane.public_ip} ansible_user=ubuntu ansible_ssh_private_key_file=${pathexpand("~/.ssh/awskey.pem")}
EOF

}
